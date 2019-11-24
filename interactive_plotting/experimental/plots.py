#!/usr/bin/env python3

from ..utils import *

from pandas.api.types import is_categorical_dtype, is_categorical, \
                             is_numeric_dtype, is_bool_dtype, \
                             is_datetime64_any_dtype, is_string_dtype, \
                             infer_dtype
from collections import OrderedDict as odict
from datashader.colors import *
from bokeh.palettes import Viridis256
from holoviews.streams import Selection1D
from holoviews.operation import decimate
from holoviews.operation.datashader import datashade, dynspread, rasterize, spread

import numpy as np
import pandas as pd
import datashader as ds
import holoviews as hv
import warnings


def pad(minn, maxx, padding=0.1):
    if minn > maxx:
        maxx, minn = minn, maxx
    delta = maxx - minn

    return minn - (delta * padding), maxx + (delta * padding)

def pad(minn, maxx, padding=0.1):
    if minn > maxx:
        maxx, minn = minn, maxx
    delta = maxx - minn

    return minn - (delta * padding), maxx + (delta * padding)

def minmax(component, perc=None, is_sorted=False):
    if perc is not None:
        assert len(perc) == 2, 'Percentile must be of length 2.'
        component = np.clip(component, *np.percentile(component, sorted(perc)))

    return (np.nanmin(component), np.nanmax(component)) if not is_sorted else (component[0], component[-1])


def scatter2(adata, x, y, color=None, order_key=None, indices=None, subsample='datashade', use_raw=False,
             size=5, jitter=None, perc=None, cmap=None,
             hover_keys=None, hover_dims=(10, 10),
             keep_frac=0.2, steps=40,
             seed=None, use_original_limits=False,
             legend_loc='top_right', show_legend=True, plot_height=600, plot_width=600):
    '''
    adata: anndata.AnnData
    x:
    y:
    color:
    order_key:
    indices:
    subsample:
    use_raw:
    size:
    jitter:
    perc:
    hover_keys:
    hover_dims:
    keep_frac:
    steps:
    seed:
    use_original_limits:
    legend_loc:
    show_legend:
    plot_height:
    plot_width:

    '''

    if hover_keys is not None:
        for h in hover_keys:
            assert h in adata.obs, f'Hover key `{h}` not found in `adata.obs`.'

    if perc is not None:
        assert len(perc) == 2, f'`perc` must be of length `2`, found: `{len(perc)}`.'
        assert all((p is not None for p in perc)), '`perc` cannot contain `None`.'
        perc = sorted(perc)

    assert len(hover_dims) == 2, f'Expected `hover_dims` to be of length `2`, found `{len(hover_dims)}`.'
    assert all((isinstance(d, int) for d in hover_dims)), 'All of `hover_dims` must be of type `int`.'
    assert all((d > 1 for d in hover_dims)), 'All of `hover_dims` must be `> 1`.'

    adata_mraw = get_mraw(adata)
    if adata_mraw is adata:
        warnings.warn('Failed fetching the `.raw`. attribute of `adata`.')

    if indices is None:
        indices = np.arange(adata_mraw.n_obs)
    adata_mraw = adata_mraw[indices, :]

    xlim, ylim = None, None
    if order_key is not None:
        assert order_key in adata.obs, f'`{order_key}` not found in `adata.obs`.'
        ixs = np.argsort(adata.obs[order_key][indices])
    else:
        ixs = np.arange(adata_mraw.n_obs)

    if x is None:
        if order_key is not None:
            x, xlabel = adata.obs[order_key][indices][ixs], order_key
        else:
            x, xlabel = ixs, 'index'  # jitter
    else:
        x, xlabel, xlim = get_xy_data(x, adata, adata_mraw, indices, use_original_limits)

    y, ylabel, ylim = get_xy_data(y, adata, adata_mraw, indices, use_original_limits, inc=1)

    # jitter
    if jitter is not None:
        msg = 'Using `jitter` != `None` and `use_original_limits=True` can negatively impact the limits.'
        if isinstance(jitter, (tuple, list)):
            assert len(jitter) == 2, f'`jitter` must be of length `2`, found `{len(jitter)}`.'
            if any((j is not None for j in jitter)) and use_original_limits:
                warnings.warn(msg)
        else:
            assert isinstance(jitter, float), 'Expected` jitter` to be of type `float`, found `{type(jitter).__name__}`.'
            warnings.warn(msg)

    x = x.astype(np.float64)
    y = y.astype(np.float64)

    if color is not None:
        if color in adata.obs:
            condition = adata.obs[color][indices][ixs]
        else:
            if isinstance(color, int):
                color = adata_mraw.var_names[color]
            assert color in adata_mraw.var_names
            condition = adata_mraw.obs_vector(color)[ixs]
    else:
        condition = None

    hover = None
    if hover_keys is not None:
        hover = {'index':  ixs}
        for key in hover_keys:
            hover[key] = adata.obs[key][indices][ixs]

    return _scatter(adata, x=x.copy(),
                    y=y.copy(),
                    condition=condition,
                    by=color,
                    xlabel=xlabel,
                    ylabel=ylabel,
                    title=color,
                    hover=hover,
                    jitter=jitter,
                    perc=perc,
                    xlim=xlim,
                    ylim=ylim,
                    hover_width=hover_dims[1],
                    hover_height=hover_dims[0],
                    subsample=subsample, steps=steps, keep_frac=keep_frac, seed=seed, legend_loc=legend_loc,
                    size=size, cmap=cmap, show_legend=show_legend, plot_height=plot_height, plot_width=plot_width)


def _scatter(adata, x, y, condition=None, by=None, subsample='datashade', steps=40, keep_frac=0.2,
             seed=None, legend_loc='top_right', size=4, xlabel=None, ylabel=None, title=None,
             use_raw=True, hover=None,
             hover_width=10,
             hover_height=10,
             jitter=None,
             perc=None,
             xlim=None,
             ylim=None,
             cmap=None, show_legend=True, plot_height=400, plot_width=400):
    '''
    Scatter plot for categorical observations. TODO: update docs, maybe not pass adata

    Params
    --------
    adata: anndata.Anndata
        anndata object
    subsample: Str, optional (default: `'datashade'`)
        subsampling strategy for large data
        possible values are `None, 'none', 'datashade', 'decimate', 'density', 'uniform'`
        using `subsample='datashade'` is preferred over other options since it does not subset
        when using `subsample='datashade'`, colorbar is not visible
        `'density'` and `'uniform'` use first element of `bases` for their computation
    steps: Union[Int, Tuple[Int, Int]], optional (default: `40`)
        step size when the embedding directions
        larger step size corresponds to higher density of points
    keep_frac: Float, optional (default: `0.2`)
        number of observations to keep when `subsample='decimate'`
    lazy_loading: Bool, optional (default: `False`)
        only visualize when necessary
        for notebook sharing, consider using `lazy_loading=False`
    sort: Bool, optional (default: `True`)
        whether sort the `genes`, `obs_keys` and `obsm_keys`
        in ascending order
    skip: Bool, optional (default: `True`)
        skip all the keys not found in the corresponding collections
    seed: Int, optional (default: `None`)
        random seed, used when `subsample='decimate'``
    legend_loc: Str, optional (default: `top_right`)
        position of the legend
    cols: Int, optional (default: `None`)
        number of columns when plotting bases
        if `None`, use togglebar
    size: Int, optional (default: `4`)
        size of the glyphs
        works only when `subsample!='datashade'`
    cmap: List[Str], optional (default: `datashader.colors.Sets1to3`)
        categorical colormap in hex format
    plot_height: Int, optional (default: `400`)
        height of the plot in pixels
    plot_width: Int, optional (default: `400`)
        width of the plot in pixels

    Returns
    --------
    plot: panel.panel
        holoviews plot wrapped in `panel.panel`
    '''

    assert keep_frac >= 0 and keep_frac <= 1, f'`keep_perc` must be in interval `[0, 1]`, got `{keep_frac}`.'
    # assert subsample in ALL_SUBSAMPLING_STRATEGIES, f'Invalid subsampling strategy `{subsample}`. Possible values are `{ALL_SUBSAMPLING_STRATEGIES}`.'
    adata_mraw = get_mraw(adata)

    if subsample == 'uniform':
        cb_kwargs = {'steps': steps}
    elif subsample == 'density':
        cb_kwargs = {'size': int(keep_frac * adata.n_obs), 'seed': seed}
    else:
        cb_kwargs = {}

    categorical = False
    if condition is None:
        cmap = ['black'] * len(x) if subsample == 'datashade' else 'black'
    elif is_categorical(condition):
        categorical = True
        cmap = Sets1to3 if cmap is None else cmap
        cmap = odict(zip(condition.cat.categories, adata.uns.get(f'{by}_colors', cmap)))
    else:
        cmap = Viridis256 if cmap is None else cmap

    jitter_x, jitter_y = None, None
    if isinstance(jitter, (tuple, list)):
        assert len(jitter) == 2, f'`jitter` must be of length `2`, found `{len(jitter)}`.'
        jitter_x, jitter_y = jitter
    elif jitter is not None:
        jitter_x, jitter_y = jitter, jitter

    if jitter_x is not None:
        x += np.random.normal(0, jitter_x, size=x.shape)
    if jitter_y is not None:
        y += np.random.normal(0, jitter_y, size=y.shape)

    data = {'x': x, 'y': y}
    vdims = []
    if condition is not None:
        data['z'] = condition
        vdims.append('z')

    hovertool = None
    if hover is not None:
        for k, dt in hover.items():
            vdims.append(k)
            data[k] = dt
        hovertool = HoverTool(tooltips=[(key.capitalize(), f'@{key}')
                                        for key in (['index'] if subsample == 'datashade' else hover.keys())])

    if vdims == []:
        vdims = None

    if xlim is None:
        xlim = pad(*minmax(x))
    if ylim is None:
        ylim = pad(*minmax(y))

    scatter = (hv.Scatter(data, kdims=[('x', 'x' if xlabel is None else xlabel),
                                       ('y', 'y' if ylabel is None else ylabel)], vdims=vdims)
               .sort(vdims)
               .opts(size=size, xlim=xlim, ylim=ylim))

    if categorical:
        scatter = scatter.opts(cmap=cmap, color='z', show_legend=show_legend, legend_position=legend_loc)
    elif 'z' in data:
        scatter = scatter.opts(cmap=cmap, color='z',
                               clim=tuple(map(float, minmax(data['z'], perc))),
                               colorbar=True,
                               colorbar_opts={'width': 20})
    else:
        scatter = scatter.opts(color='black')

    legend = None
    if subsample == 'datashade':
        subsampled = dynspread(datashade(scatter, aggregator=(ds.count_cat('z') if categorical else ds.mean('z')) if vdims is not None else None,
                                      color_key=cmap, cmap=cmap,
                                      streams=[hv.streams.RangeXY(transient=True), hv.streams.PlotSize],
                                      min_alpha=255).opts(axiswise=True, framewise=True), threshold=0.8, max_px=5)
        if show_legend and categorical:
            legend = hv.NdOverlay({k: hv.Points([0, 0], label=str(k)).opts(size=0, color=v)
                                   for k, v in cmap.items()})
        if hover is not None:
            t = hv.util.Dynamic(rasterize(scatter, width=hover_width, height=hover_height, streams=[hv.streams.RangeXY],
                                          aggregator=ds.reductions.min('index')), operation=hv.QuadMesh)\
                                              .opts(tools=[hovertool], axiswise=True, framewise=True,
                                                    alpha=0, hover_alpha=0.25,
                                                    height=plot_height, width=plot_width)
            scatter = t * subsampled
        else:
            scatter = subsampled

    elif subsample == 'decimate':
        scatter = decimate(scatter, max_samples=int(adata.n_obs * keep_frac),
                           streams=[hv.streams.RangeXY(transient=True)], random_seed=seed)

    if legend is not None:
        scatter = (scatter * legend).opts(legend_position=legend_loc)

    scatter = scatter.opts(title=title if title is not None else '',
                           frame_height=plot_height, frame_width=plot_width, xlim=xlim, ylim=ylim)
    return scatter.opts(tools=[hovertool]) if hovertool is not None else scatter


def _heatmap(adata, genes, group='louvain', sort_genes=True, use_raw=False,
            xrotation=90, yrotation=0, colorbar=True,
            plot_width=600, plot_height=300, cmap=Viridis256,
            hover=True, agg_fns=['mean']):
    '''
    Params
    -------
    adata: anndata.AnnData
        adata object
    genes: List[Str]
        genes in `adata.var_names`
    group_key: Str
        key in `adata.obs`, must be categorical
    show_scatterplot: Bool, optional (default: `False`)
        whether to show gene expression
        in pseudotime for selected gene - TODO: make more general

    Returns
    -------
    '''
    assert group in adata.obs
    assert is_categorical(adata.obs[group])
    assert len(agg_fns) > 0

    for g in genes:
        assert g in adata.var_names, f'Unable to find gene `{g}` in `adata.var_names`.'

    genes = sorted(genes) if sort_genes else genes
    groups = sorted(list(adata.obs[group].cat.categories))

    ad = adata[np.in1d(adata.obs[group], groups)][:, genes]
    df = pd.DataFrame(get_mraw(ad).X, columns=genes)
    df['group'] = list(map(str, ad.obs[group]))
    groupby = df.groupby('group')

    vals = {agg_fn: groupby.agg(agg_fn) for agg_fn in agg_fns}
    z_value = vals.pop(agg_fns[0])

    x = hv.Dimension('x', label='Gene')
    y = hv.Dimension('y', label='Group')
    z = hv.Dimension('z', label='Expression')
    vdims = [(k, k.capitalize()) for k in vals.keys()]

    heatmap = hv.HeatMap({'x': np.array(genes), 'y': np.array(groups), 'z': z_value, **vals},
                         kdims=[('x', 'Gene'), ('y', 'Group')],
                         vdims=[('z', 'Expression')] + vdims).opts(tools=['box_select'] + (['hover'] if hover else []),
                                                                   xrotation=xrotation, yrotation=yrotation)

    return heatmap.opts(frame_width=plot_width, frame_height=plot_height, colorbar=colorbar, cmap=cmap)

def heatmap(adata, genes, groups=None, compare='genes', agg_fns=['mean', 'var'], use_raw=False,
            order_keys=[], hover=True, show_highlight=False, show_scatter=False,
            subsample='decimate', keep_frac=0.2, seed=None,
            xrotation=90, yrotation=0, colorbar=True, cont_cmap=Viridis256,
            width=600, height=200, **scatter_kwargs):
    '''
    Plot a heatmap with groups selected from drop-down menu.

    adata: anndata.AnnData
        adata object
    genes: List[Str]
        genes in `adata.var_names`
    groups: List[Str], optional (default: `None`)
        categorical observation in `adata.obs`,
        if `None`, get all groups from `adata.obs`
    compare: Union[`'genes'`, `'bases'`, `'order'`]
        only used when `show_scatterplot=True`,
        creates
        if `'genes'`, clicking a gene in highlighted heatmap
            drow-down menu will contain values from `genes` and clicking
            a gene in highlighted heatmap will plot scatterplot of the 2
            genes with groups colored in
        if `'basis'`
            drow-down menu will contain available bases and clicking
            a gene in highlighted heatmap will plot the gene in the selected
            embedding with its expression colored in
        if `'order'`:
            drop-down menu will contain values from `order_keys`,
            and clicking on a gene in highlighted heatmap will plot its expression
            in selected order
    agg_fns: List[Str], optional (default: `['mean', 'var']`
        names of pandas' aggregation functions, such `'min'`, ...
        the first function specified is mapped to colors
    use_raw: Bool, optional (default: `False`)
        whether to use `.raw` for gene expression
    order_keys: List[Str], optional (default: `None`)
        keys in `adata.obs`, used when `compare='order'`
    hover: Bool, optional (default: `True`)
        whether to display hover information over the heatmap
    show_highlight: Bool, optional (default: `False`)
        whether to show when using boxselect
    show_scatter: Bool, optional (default: `False`)
        whether to show a scatterplot,
        if `True`, overrides `show_highlight=False`
    subsample: Union[Str, NoneType], optional (default: `'decimate'`)
        how to subsample the data
    keep_frac: Float, optional (default: `0.2`)
        fraction of cells to keep, used when `subsample='decimate'`
    seed: Union[Float, NoneType], optional (default: `None`)
        random seed, used when `subsample='decimate'`
    xrotation: Int, optional (default: `90`)
        rotation of labels on x-axis
    yrotation: Int, optional (default: `0`)
        rotation of labels on y-axis
    colorbar: Bool, optional (default: `True`)
        whether to show colorbar
    cont_cmap: Union[List[Str], NoneType], optional (default, `None`)
        colormap of the heatmap,
        if `None`, use `Viridis256`
    height: Int, optional (default: `600`)
        height of the heatmap
    width: Int, optional (default: `200`)
        width of the heatmap
    **scatter_kwargs:
        additional argument for `ipl.experimental.scatter`,
        only used when `show_scatter=True`
    '''

    def _highlight(group, index):
        original = hm[group]
        if not index:
            return original

        return original.iloc[sorted(index)]

    def _scatter(group, which, gwise, x, y):
        indices = adata.obs[group] == y if gwise else np.isin(adata.obs[group], highlight[group].data['y'])
        if is_ordered:
            scatter_kwargs['order_key'] = which
            x, y = None, x
        elif f'X_{which}' in adata.obsm:
            group = x
            x, y = which, which
        else:
            x, y = x, which

        return scatter2(adata, x=x, y=y, color=group, indices=indices,
                        jitter=0.01, **scatter_kwargs).opts(axiswise=True, framewise=True)

    is_ordered = False
    scatter_kwargs['use_original_limits'] = True
    scatter_kwargs['subsample'] = None
    if 'plot_width' not in scatter_kwargs:
        scatter_kwargs['plot_width'] = 300
    if 'plot_height' not in scatter_kwargs:
        scatter_kwargs['plot_height'] = 300

    if groups is not None:
        assert len(groups) > 0, f'Number of groups `> 1`.'
    else:
        groups = [k for k in adata.obs.keys() if is_categorical(adata.obs[k])]

    kdims=[hv.Dimension('Group',values=groups, selected=groups[0])]

    hm = hv.DynamicMap(lambda g: _heatmap(adata, genes, agg_fns=agg_fns, group=g,
                                          hover=hover, use_raw=use_raw,
                                          cmap=cont_cmap,
                                          xrotation=xrotation, yrotation=yrotation,
                                          colorbar=colorbar), kdims=kdims).opts(frame_height=height,
                                                                                frame_width=width)
    if not show_highlight and not show_scatter:
        return hm

    highlight = hv.DynamicMap(_highlight, kdims=kdims, streams=[Selection1D(source=hm)])
    if not show_scatter:
        return (hm + highlight).cols(1)

    if compare == 'basis':
        basis = [b.lstrip('X_') for b in adata.obsm.keys()]
        kdims += [hv.Dimension('Components', values=basis, selected=basis[0])]
    elif compare == 'genes':
        kdims += [hv.Dimension('Genes', values=genes, selected=genes[0])]
    else:
        is_ordered = True
        k = scatter_kwargs.pop('order_key', None)
        assert k is not None or order_keys != [], f'No order keys specified.'

        if k not in order_keys:
            order_keys.append(k)

        for k in order_keys:
            assert k in adata.obs, f'Order key `{k}` not found in `adata.obs`.'

        kdims += [hv.Dimension('Order', values=order_keys)]

    kdims += [hv.Dimension('Groupwise', type=bool, values=[True, False], default=True)]

    scatter_stream = hv.streams.Tap(source=highlight, x=genes[0], y=adata.obs[groups[0]].values[0])
    scatter = hv.DynamicMap(_scatter, kdims=kdims, streams=[scatter_stream])

    if subsample == 'decimate':
        scatter = decimate(scatter, max_samples=int(adata.n_obs * keep_frac),
                           streams=[hv.streams.RangeXY(transient=True)], random_seed=seed)

    return (hm + highlight + scatter).cols(1)
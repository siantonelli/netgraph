#!/usr/bin/env python
"""
TODO:
- suppress warnings for divide by zero on diagonal -- masked arrays?
- ensure that the adjacency matrix has the correct dimensions even is one of the nodes is unconnected
"""

import numpy as np


from _utils import (
    warnings,
    _edge_list_to_adjacency_matrix,
    _edge_list_to_adjacency_list,
    _get_subgraph,
    _get_unique_nodes,
    _flatten,
)


BASE_NODE_SIZE = 1e-2
BASE_EDGE_WIDTH = 1e-2


def get_fruchterman_reingold_layout(edge_list,
                                    k                   = None,
                                    scale               = None,
                                    origin              = None,
                                    initial_temperature = 1.,
                                    total_iterations    = 50,
                                    node_size           = None,
                                    node_positions      = None,
                                    fixed_nodes         = None,
                                    *args, **kwargs
):
    """
    Arguments:
    ----------

    edge_list : m-long iterable of 2-tuples or equivalent (such as (m, 2) ndarray)
        List of edges. Each tuple corresponds to an edge defined by (source, target).

    origin : (float x, float y) tuple or None (default None -> (0, 0))
        The lower left hand corner of the bounding box specifying the extent of the layout.
        If None is given, the origin is placed at (0, 0).

    scale : (float delta x, float delta y) or None (default None -> (1, 1))
        The width and height of the bounding box specifying the extent of the layout.
        If None is given, the scale is set to (1, 1).

    k : float or None (default None)
        Expected mean edge length. If None, initialized to the sqrt(area / total nodes).

    total_iterations : int (default 50)
        Number of iterations.

    initial_temperature: float (default 1.)
        Temperature controls the maximum node displacement on each iteration.
        Temperature is decreased on each iteration to eventually force the algorithm
        into a particular solution. The size of the initial temperature determines how
        quickly that happens. Values should be much smaller than the values of `scale`.

    node_size : scalar or (n,) or dict key : float (default 0.)
        Size (radius) of nodes.
        Providing the correct node size minimises the overlap of nodes in the graph,
        which can otherwise occur if there are many nodes, or if the nodes differ considerably in size.
        NOTE: Value is rescaled by BASE_NODE_SIZE (1e-2) to give comparable results to layout routines in igraph and networkx.

    node_positions : dict key : (float, float) or None (default None)
        Mapping of nodes to their (initial) x,y positions. If None are given,
        nodes are initially placed randomly within the bounding box defined by `origin`
        and `scale`.

    fixed_nodes : list of nodes
        Nodes to keep fixed at their initial positions.

    Returns:
    --------
    node_positions : dict key : (float, float)
        Mapping of nodes to (x,y) positions

    """

    # This is just a wrapper around `_fruchterman_reingold`, which implements (the loop body of) the algorithm proper.
    # This wrapper handles the initialization of variables to their defaults (if not explicitely provided),
    # and checks inputs for self-consistency.

    if origin is None:
        if node_positions:
            minima = np.min(list(node_positions.values()), axis=0)
            origin = np.min(np.stack([minima, np.zeros_like(minima)], axis=0), axis=0)
        else:
            origin = np.zeros((2))
    else:
        # ensure that it is an array
        origin = np.array(origin)

    if scale is None:
        if node_positions:
            delta = np.array(list(node_positions.values())) - origin[np.newaxis, :]
            maxima = np.max(delta, axis=0)
            scale = np.max(np.stack([maxima, np.ones_like(maxima)], axis=0), axis=0)
        else:
            scale = np.ones((2))
    else:
        # ensure that it is an array
        scale = np.array(scale)

    assert len(origin) == len(scale), \
        "Arguments `origin` (d={}) and `scale` (d={}) need to have the same number of dimensions!".format(len(origin), len(scale))
    dimensionality = len(origin)

    unique_nodes = _get_unique_nodes(edge_list)
    total_nodes = len(unique_nodes)

    if node_positions is None: # assign random starting positions to all nodes
        node_positions_as_array = np.random.rand(total_nodes, dimensionality) * scale + origin
    else:
        # 1) check input dimensionality
        dimensionality_node_positions = np.array(list(node_positions.values())).shape[1]
        assert dimensionality_node_positions == dimensionality, \
            "The dimensionality of values of `node_positions` (d={}) must match the dimensionality of `origin`/ `scale` (d={})!".format(dimensionality_node_positions, dimensionality)

        is_valid = _is_within_bbox(list(node_positions.values()), origin=origin, scale=scale)
        if not np.all(is_valid):
            error_message = "Some given node positions are not within the data range specified by `origin` and `scale`!"
            error_message += "\nOrigin : {}, {}".format(*origin)
            error_message += "\nScale  : {}, {}".format(*scale)
            for ii, (node, position) in enumerate(node_positions.items()):
                if not is_valid[ii]:
                    error_message += "\n{} : {}".format(node, position)
            raise ValueError(error_message)

        # 2) handle discrepancies in nodes listed in node_positions and nodes extracted from edge_list
        if set(node_positions.keys()) == set(unique_nodes):
            # all starting positions are given;
            # no superfluous nodes in node_positions;
            # nothing left to do
            pass
        else:
            # some node positions are provided, but not all
            for node in unique_nodes:
                if not (node in node_positions):
                    warnings.warn("Position of node {} not provided. Initializing to random position within frame.".format(node))
                    node_positions[node] = np.random.rand(2) * scale + origin

            # unconnected_nodes = []
            for node in node_positions:
                if not (node in unique_nodes):
                    # unconnected_nodes.append(node)
                    warnings.warn("Node {} appears to be unconnected. No position is computed for this node.".format(node))
                    del node_positions[node]

        node_positions_as_array = np.array(list(node_positions.values()))

    if node_size is None:
        node_size = np.zeros((total_nodes))
    elif isinstance(node_size, (int, float)):
        node_size = BASE_NODE_SIZE * node_size * np.ones((total_nodes))
    elif isinstance(node_size, dict):
        node_size = np.array([BASE_NODE_SIZE * node_size[node] if node in node_size else 0. for node in unique_nodes])

    if fixed_nodes is None:
        is_mobile = np.ones((len(unique_nodes)), dtype=np.bool)
    else:
        is_mobile = np.array([False if node in fixed_nodes else True for node in unique_nodes], dtype=np.bool)

    adjacency = _edge_list_to_adjacency_matrix(edge_list)

    # Forces in FR are symmetric.
    # Hence we need to ensure that the adjacency matrix is also symmetric.
    adjacency = adjacency + adjacency.transpose()

    if k is None:
        area = np.product(scale)
        k = np.sqrt(area / float(total_nodes))

    temperatures = _get_temperature_decay(initial_temperature, total_iterations)

    # --------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------
    # main loop

    for ii, temperature in enumerate(temperatures):
        node_positions_as_array[is_mobile] = _fruchterman_reingold(adjacency, node_positions_as_array,
                                                                   origin      = origin,
                                                                   scale       = scale,
                                                                   temperature = temperature,
                                                                   k           = k,
                                                                   node_radii  = node_size,
        )[is_mobile]

    node_positions_as_array =  _rescale_to_frame(node_positions_as_array, origin, scale)

    # --------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------
    # format output
    node_positions = dict(zip(unique_nodes, node_positions_as_array))

    return node_positions


def _is_within_bbox(points, origin, scale):
    return np.all((points >= origin) * (points <= origin + scale), axis=1)


def _get_temperature_decay(initial_temperature, total_iterations, mode='quadratic', eps=1e-9):
    x = np.linspace(0., 1., total_iterations)
    if mode == 'quadratic':
        y = (x - 1.)**2 + eps
    elif mode == 'linear':
        y = (1. - x) + eps
    else:
        raise ValueError("Argument `mode` one of: 'linear', 'quadratic'.")
    return initial_temperature * y


def _fruchterman_reingold(adjacency, node_positions, origin, scale, temperature, k, node_radii):
    """
    Inner loop of Fruchterman-Reingold layout algorithm.
    """

    # compute distances and unit vectors between nodes
    delta        = node_positions[None, :, ...] - node_positions[:, None, ...]
    distance     = np.linalg.norm(delta, axis=-1)

    # assert np.sum(distance==0) - np.trace(distance==0) > 0, "No two node positions can be the same!"

    # alternatively: (hack adapted from igraph)
    if np.sum(distance==0) - np.trace(distance==0) > 0: # i.e. if off-diagonal entries in distance are zero
        warnings.warn("Some nodes have the same position; repulsion between the nodes is undefined.")
        rand_delta = np.random.rand(*delta.shape) * 1e-9
        is_zero = distance <= 0
        delta[is_zero] = rand_delta[is_zero]
        distance = np.linalg.norm(delta, axis=-1)

    # subtract node radii from distances to prevent nodes from overlapping
    distance -= node_radii[None, :] + node_radii[:, None]

    # prevent distances from becoming less than zero due to overlap of nodes
    distance[distance <= 0.] = 1e-6 # 1e-13 is numerical accuracy, and we will be taking the square shortly

    with np.errstate(divide='ignore', invalid='ignore'):
        direction = delta / distance[..., None] # i.e. the unit vector

    # calculate forces
    repulsion    = _get_fr_repulsion(distance, direction, k)
    attraction   = _get_fr_attraction(distance, direction, adjacency, k)
    displacement = attraction + repulsion

    # limit maximum displacement using temperature
    displacement_length = np.linalg.norm(displacement, axis=-1)
    displacement = displacement / displacement_length[:, None] * np.clip(displacement_length, None, temperature)[:, None]

    node_positions = node_positions + displacement

    return node_positions


def _get_fr_repulsion(distance, direction, k):
    with np.errstate(divide='ignore', invalid='ignore'):
        magnitude = k**2 / distance
    vectors   = direction * magnitude[..., None]
    # Note that we cannot apply the usual strategy of summing the array
    # along either axis and subtracting the trace,
    # as the diagonal of `direction` is np.nan, and any sum or difference of
    # NaNs is just another NaN.
    # Also we do not want to ignore NaNs by using np.nansum, as then we would
    # potentially mask the existence of off-diagonal zero distances.
    vectors   = _set_diagonal(vectors, 0)
    return np.sum(vectors, axis=0)


def _get_fr_attraction(distance, direction, adjacency, k):
    magnitude = 1./k * distance**2 * adjacency
    vectors   = -direction * magnitude[..., None] # NB: the minus!
    vectors   = _set_diagonal(vectors, 0)
    return np.sum(vectors, axis=0)


def _rescale_to_frame(node_positions, origin, scale):
    node_positions = node_positions.copy() # force copy, as otherwise the `fixed_nodes` argument is effectively ignored
    node_positions -= np.min(node_positions, axis=0)
    node_positions /= np.max(node_positions, axis=0)
    node_positions *= scale[None, ...]
    node_positions += origin[None, ...]
    return node_positions


def _clip_to_frame(node_positions, origin, scale):
    # This function does not work well with the FR algorithm:
    # If the new node positions exceed the frame in more than one dimension,
    # they end up being placed on a corner of the frame.
    # If more than one node ends up in one of the corners, we are in trouble,
    # as then the distance between them becomes zero.
    for ii, (minimum, maximum) in enumerate(zip(origin, origin+scale)):
        node_positions[:, ii] = np.clip(node_positions[:, ii], minimum, maximum)
    return node_positions


def _set_diagonal(square_matrix, value=0):
    n = len(square_matrix)
    is_diagonal = np.diag(np.ones((n), dtype=np.bool))
    square_matrix[is_diagonal] = value
    return square_matrix


# def get_positions_for_unconnected_nodes(unconnected_nodes, other_node_positions):
#     """
#     Determine a good position of unconnected nodes.
#     Currently, we place these nodes on the periphery, which we define as the area
#     just outside the circle covering all positions in `other_node_positions`.

#     TODO:
#     Place the nodes in empty regions of the periphery.
#     For example, one could use a force directed layout to achieve this.
#     1) Tether each unconnected node to the centroid.
#     2) Compute radial force give by other nodes; iterate for a few rounds.

#     Arguments:
#     ----------
#     unconnected_nodes : list
#         The nodes for which we need to find positions.

#     other_node_positions : dict node ID : (float, float)
#         The positions of all other nodes.

#     Returns:
#     --------
#     node_positions : dict node ID : (float, float)
#         The positions of the unconnected nodes.

#     """

#     xy = np.array(list(other_node_positions.values()))
#     centroid = np.mean(xy, axis=0)
#     delta = xy - centroid[np.newaxis, :]
#     distance = np.sqrt(np.sum(delta**2, axis=1))
#     radius = np.max(distance)

#     node_positions = dict()
#     for node in unconnected_nodes:
#         node_positions[node] = _get_random_point_on_a_circle(centroid, radius*1.1)

#     return node_positions


# def _get_random_point_on_a_circle(origin, radius):
#     random_angle = 2 * np.pi * np.random.random()
#     return _get_point_on_a_circle(origin, radius, angle)


# def _get_point_on_a_circle(origin, radius, angle):
#     x0, y0 = origin
#     x = x0 + radius * np.cos(angle)
#     y = y0 + radius * np.sin(angle)
#     return np.array([x, y])








def get_layout_for_multiple_components(edge_list,
                                       unconnected_nodes         = None,
                                       node_size                 = None,
                                       origin                    = (0, 0),
                                       scale                     = (1, 1),
                                       component_layout_function = get_fruchterman_reingold_layout,
                                       *args, **kwargs):
    """
    Many graph layout algorithms assume that the graph consists of a single connected component.
    As a consequence, they fail when that is not the case.
    This function tries to work around this issue by determining suitable bounding box
    dimensions and placement for each component in the graph, and then
    computing the layout of each individual component given the constraint of the
    bounding box.

    The bounding boxes

    Arguments:
    ----------
    edge_list : list of (source node, target node) tuples
        The graph to plot.
    unconnected_nodes : list of nodes
        Additional nodes to plot, that are unconnected and hence are not present
        in the edge list.
    origin : D-tuple or None (default None, which implies (0, 0))
        Bottom left corner of the frame / canvas containing the graph.
        If None, it defaults to (0, 0) or the minimum of `node_positions`
        (whichever is smaller).
    scale : D-tuple or None (default None, which implies (1, 1)).
        Width, height, etc of the frame. If None, it defaults to (1, 1) or the
        maximum distance of nodes in `node_positions` to the `origin`
        (whichever is greater).

    Returns:
    --------
    node_positions : dict node : (float x, float y)
        The position of all nodes in the graph.

    """

    adjacency_list = _edge_list_to_adjacency_list(edge_list)
    components = _get_connected_components(adjacency_list)
    components = components + [set([node]) for node in unconnected_nodes]
    bboxes = _get_component_bboxes(components, origin, scale)

    # # for debugging
    # import matplotlib.pyplot as plt
    # from matplotlib.patches import Rectangle
    # fig, ax = plt.subplots(1,1)
    # for bbox in bboxes:
    #     ax.add_artist(Rectangle(bbox[:2], bbox[2], bbox[3], color=np.random.rand(3)))
    # ax.set_xlim(0, 1)
    # ax.set_ylim(0, 1)
    # plt.show()

    node_positions = dict()
    for ii, (component, bbox) in enumerate(zip(components, bboxes)):
        if len(component) > 1:
            subgraph = _get_subgraph(edge_list, component)
            component_node_positions = component_layout_function(subgraph, origin=bbox[:2], scale=bbox[2:], *args, **kwargs)
            node_positions.update(component_node_positions)
        else:
            # component is a single node, which we can simply place at the centre of the bounding box
            node_positions[component.pop()] = (bbox[0] + 0.5 * bbox[2], bbox[1] + 0.5 * bbox[3])

    return node_positions


def _get_connected_components(adjacency_list):
    """
    Get the connected components given a graph in adjacency list format.

    Arguments:
    ----------
    adjacency_list : dict node ID : set of node IDs
        Adjacency list, i.e. a mapping from each node to its neighbours.

    Returns:
    --------
    components : list of sets of node IDs

    """

    components = []
    not_visited = set(list(adjacency_list.keys()))
    while not_visited: # i.e. while stack is non-empty (empty set is interpreted as `False`)
        start = not_visited.pop()
        component = _dfs(adjacency_list, start)
        components.append(component)

        #  remove nodes that are in the component that we just found
        for node in component:
            try:
                not_visited.remove(node)
            except KeyError:
                # KeyErrors occur when we try to remove
                # 1) the start node (which we already popped), or
                # 2) leaf nodes, i.e. nodes with no outgoing edges
                pass

    # Often, we are only interested in the largest component,
    # hence we return the list of components sorted by size, largest first.
    components = sorted(components, key=len, reverse=True)

    return components


def _dfs(adjacency_list, start, visited=None):
    if visited is None:
        visited = set()
    visited.add(start)
    for node in adjacency_list[start] - visited:
        if node in adjacency_list:
            _dfs(adjacency_list, node, visited)
        else: # otherwise no outgoing edge
            visited.add(node)
    return visited


def _get_component_bboxes(components, origin, scale, power=0.8, pad_by=0.05):
    # leave rpack an optional dependency for the time being
    try:
        import rpack
    except ImportError:
        error_msg = "Plotting of multiple components only supported when rpack is installed.\n"
        error_msg += "You can install rpack with:\n"
        error_msg += "pip install rectangle-packer"
        raise ImportError(error_msg)

    relative_dimensions = [_get_bbox_dimensions(len(component), power=power) for component in components]

    # Add a padding between boxes, such that nodes cannot end up touching in the final layout.
    # We choose a padding proportional to the dimensions of the largest box.
    maximum_dimensions = np.max(relative_dimensions, axis=0)
    pad_x, pad_y = pad_by * maximum_dimensions
    padded_dimensions = [(width + pad_x, height + pad_y) for (width, height) in relative_dimensions]

    # rpack only works on integers;
    # multiply by some large scalar to retain some precision;
    # NB: for some strange reason, rpack's running time is sensitive to the size of the boxes
    # TODO find alternative to rpack
    scalar = 10
    integer_dimensions = [(int(scalar*width), int(scalar*height)) for width, height in padded_dimensions]
    origins = rpack.pack(integer_dimensions) # NB: rpack claims to return upper-left corners, when it actually returns lower-left corners

    bboxes = [(x, y, scalar*width, scalar*height) for (x, y), (width, height) in zip(origins, relative_dimensions)]

    # rescale boxes to canvas
    bboxes = _rescale_bboxes_to_canvas(bboxes, origin, scale)

    return bboxes


def _get_bbox_dimensions(n, power=0.5):
    # TODO: factor in the dimensions of the canvas
    # such that the rescaled boxes are approximately square
    return (n**power, n**power)


def _rescale_bboxes_to_canvas(bboxes, origin, scale):
    lower_left_hand_corners = [(x, y) for (x, y, _, _) in bboxes]
    upper_right_hand_corners = [(x+w, y+h) for (x, y, w, h) in bboxes]
    minimum = np.min(lower_left_hand_corners, axis=0)
    maximum = np.max(upper_right_hand_corners, axis=0)
    total_width, total_height = maximum - minimum

    # shift to (0, 0)
    min_x, min_y = minimum
    lower_left_hand_corners = [(x - min_x, y-min_y) for (x, y) in lower_left_hand_corners]

    # rescale
    scale_x = scale[0] / total_width
    scale_y = scale[1] / total_height

    lower_left_hand_corners = [(x*scale_x, y*scale_y) for x, y in lower_left_hand_corners]
    dimensions = [(w * scale_x, h * scale_y) for (_, _, w, h) in bboxes]
    rescaled_bboxes = [(x, y, w, h) for (x, y), (w, h) in zip(lower_left_hand_corners, dimensions)]

    return rescaled_bboxes


def test_get_layout_for_multiple_components():
    import matplotlib.pyplot as plt # ; plt.ion()
    from _main import draw, Graph # , InteractiveGraph
    from itertools import combinations
    import networkx as nx

    edge_list = []

    # add 100 unconnected nodes
    unconnected_nodes = list(range(100))

    # add 50 2-node components
    edge_list.extend([(ii, ii+1) for ii in range(100, 200, 2)])

    # add 33 3-node components
    for ii in range(200, 300, 3):
        edge_list.extend([(ii, ii+1), (ii, ii+2), (ii+1, ii+2)])

    # add a couple of larger components
    n = 300
    for ii in np.random.randint(3, 30, size=10):
        edge_list.extend(list(combinations(range(n, n+ii), 2)))
        n += ii

    pos = get_layout_for_multiple_components(edge_list, unconnected_nodes=unconnected_nodes)

    g = nx.Graph()
    g.add_edges_from(edge_list)
    g.add_nodes_from(unconnected_nodes)
    # nx.draw(g, pos=pos)

    draw(g, node_positions=pos, node_size=1., node_edge_width=0.1, edge_width=0.1)

    plt.show()


if __name__ == '__main__':
    test_get_layout_for_multiple_components()

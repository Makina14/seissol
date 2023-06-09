import itertools
import time
import os
from netCDF4 import Dataset
import numpy as np
from datetime import datetime
import seissolxdmf
import trimesh
import trimesh.proximity
import trimesh.ray
import trimesh.viewer
import trimesh.creation
from pyproj import Transformer
import rasterio
import bisect


def grdwrite(x, y, z, foutput):
    """
    Write a netCDF file using x, y and z
    :param x: 1D array of x coordinates
    :param y: 1D array of y coordinates
    :param z: 2D array of z values
    :param foutput: name of the outputfile
    :return: netCDF file
    """
    today = datetime.today()
    # Define the dataset and the dimensions
    dataset = Dataset(foutput, 'w', format="NETCDF4")
    dataset.createDimension('x', len(x))
    dataset.createDimension('y', len(y))

    # Create the dataset variables
    longitud = dataset.createVariable('x', 'f8', 'x')
    latitud = dataset.createVariable('y', 'f8', 'y')
    valores_interpolados = dataset.createVariable('z', 'f4', ('y', 'x'))

    # Add the data to the created variables
    longitud[:] = x
    latitud[:] = y
    valores_interpolados[:, :] = z

    # Add general information of the dataset
    dataset.Conventions = " "
    dataset.title = foutput
    dataset.history = "File written using netCDF4 Python module"
    dataset.description = "Created " + today.strftime("%d/%m/%y")
    dataset.GMT_version = "6.1.0"
    longitud.units = "degrees east"
    latitud.units = "degrees north"
    valores_interpolados.units = 'meters'

    dataset.close()

    return


def getBarycentricCoord(pto, vert_a, vert_b, vert_c):
    """
    Function returning a list of the barycentric coordinates of a 2D point within a 2D triangle

    :param pto: point within the trinagle
    :param vert_a: vertex a
    :param vert_b: vertex b
    :param vert_c: vertex c
    :return: list of the three barycentric coordinates of pto respecto to vertex a, vertex b and vertex c
    """
    ab = vert_b - vert_a
    ac = vert_c - vert_a
    ap = pto - vert_a

    normal_ac = [vert_a[1] - vert_c[1], vert_c[0] - vert_a[0]]
    normal_ab = [vert_a[1] - vert_b[1], vert_b[0] - vert_a[0]]

    bary_beta = np.dot(ap, normal_ac) / np.dot(ab, normal_ac)
    bary_gamma = np.dot(ap, normal_ab) / np.dot(ac, normal_ab)
    bary_alpha = 1.000 - bary_beta - bary_gamma

    return [bary_alpha, bary_beta, bary_gamma]


def generateMesh3DfromSeissol(path2SeissolOutput):
    """
    Return a trimesh object generated using SeisSol nodes and connectivity arrays

    :param path2SeissolOutput:  path to the file .xdmf generated by SeisSol. Same folder must contain
                                the files of the vertex and cell information
    :return: trimesh 3d object
    """
    sx = seissolxdmf.seissolxdmf(path2SeissolOutput)
    nodes_seissol3d = sx.ReadGeometry()  # nodes array
    faces_seissol3d = sx.ReadConnect()  # connectivity array
    mesh3d = trimesh.Trimesh(vertices=nodes_seissol3d,
                             faces=faces_seissol3d, process=False)  # trimesh object
    return mesh3d


def generateMesh2DfromSeissol(path2SeissolOutput):
    """
    Return a trimesh object generated using SeisSol nodes and connectivity arrays. It is projected to z=0.

    :param path2SeissolOutput:  path to the file .xdmf generated by SeisSol. Same folder must contain
                                the files of the vertex and cell information
    :return: trimesh 2d-essentially object in the sense that nodes vertical component is 0
    """
    sx = seissolxdmf.seissolxdmf(path2SeissolOutput)
    nodes_seissol3d = sx.ReadGeometry()  # nodes array
    faces_seissol3d = sx.ReadConnect()  # connectivity array
    N_nodes = len(nodes_seissol3d)

    nodos_seissol2d = np.delete(nodes_seissol3d, 2, 1)  # remove last component
    nodos_seissol2d = np.c_[nodos_seissol2d, np.zeros(N_nodes)]  # add z=0 to each node to keep working on 3D

    mesh2d = trimesh.Trimesh(vertices=nodos_seissol2d, faces=faces_seissol3d, process=False)
    return mesh2d


def mesh2dCRSconversion(mesh2d, meshCRS):
    """
    Generate a new 2D mesh in CRS WGS84

    :param mesh2d:
    :param meshCRS:
    :return: new trimesh object in the new CRS
    """
    transformer = Transformer.from_crs(meshCRS, "epsg:4326", always_xy=True)
    nodes_utm = mesh2d.vertices
    x = nodes_utm[:, 0]
    y = nodes_utm[:, 1]

    xnew, ynew = transformer.transform(x, y)

    nodes_wgs = np.array([[m, n] for m, n in zip(xnew, ynew)])
    nodes_wgs = np.c_[nodes_wgs, np.zeros(len(nodes_wgs))]

    mesh2d_wgs = trimesh.Trimesh(vertices=nodes_wgs, faces=mesh2d.faces, process=False)

    return mesh2d_wgs


def assign_nodes_values(path2SeissolOutput, mesh3d, variable, instant):
    """
    This function assigns values to the nodes of a 3D triangular mesh based on a weighted mean using
    the faces areas that contain each node as a vertex

    :param path2SeissolOutput: path to the file .xdmf generated by SeisSol. Same folder must contain
                        the files of the vertex and cell information
    :param mesh3d: trimesh 3d object
    :param variable: string name of one of the variables provided by SeisSol
    :param instant: timestep of the SeisSol output
    :return: .npy file of the assigned values to the nodes. The name is "node_values_[variable]_timestep[instant]"
    and will be saved on the current directory
    """
    sx = seissolxdmf.seissolxdmf(path2SeissolOutput)  # open the SeisSol output to read the variable
    values = sx.ReadData(variable)  # read the variable
    area_triangles = mesh3d.area_faces
    nodes_value = []
    for i in range(0, len(mesh3d.vertices)):
        shared_faces = mesh3d.vertex_faces[i]  # face indexes that have node_i in common
        shared_faces = np.delete(shared_faces, np.where(shared_faces == -1))  # remove indexes -1
        total_shared_area = 0.0
        value_acum = 0.0
        for j in range(0, len(shared_faces)):
            area_j = area_triangles[shared_faces[j]]  # adyacent face area
            v_j = values[instant][shared_faces[j]]  # variable value in the selected instant and selected face
            value_acum += v_j * area_j
            total_shared_area += area_j
        # final value to associate to the node after the weighted mean:
        final_node_value = value_acum / total_shared_area
        nodes_value.append(final_node_value)
    nodes_value = np.asarray(nodes_value)  # array containing the nodes values
    if not os.path.exists("nodes_arrays"):
        os.mkdir("nodes_arrays")
    np.save("nodes_arrays/node_values_{}_timestep{}".format(variable, instant), nodes_value)
    outfile = "node_values_{}_timestep{}.npy".format(variable, instant)
    return outfile


def interpolate_pointCloud(points, mesh2d, nodes_values):
    """
    This function assign a value to a given 2D point (z=0) within an 2D-essentially mesh (z=0).
    The assignment is based on a convex linear combination where the coefficients are the point
    barycentric coordinates and the values are those associated to the nodes of the corresponding triangle that
    contains the point

    :param points: array of dim(n,3) with last component z=-1. (x,y) coordinates must be located inside the 2D mesh!!
    :param mesh2d: trimesh triangular mesh object projected onto z=0 (all nodes must have z=0 component)
    :param nodes_values: array of dim(Nnodes,) of values associated to the mesh2d nodes
    :return: array of interpolated values
    """
    rays = trimesh.ray.ray_pyembree.RayMeshIntersector(mesh2d)  # ray object from pyembree
    # Next line cast a ray from point in the z direction and get the triangle index that intersects
    face_indexes = rays.intersects_first(points, np.array([[0., 0., 1.]]))  # list of triangles indexes
    c = 0
    interpolated_values = []
    eps = 0.0000925925925926  # ~10m
    if -1 in face_indexes:
        pos = np.where(face_indexes == -1)
        for i in pos[0]:
            point_temp = points[i]
            point_temp += eps
            new_index = rays.intersects_first(np.array([point_temp]), np.array([[0., 0., 1.]]))[0]
            face_indexes[i] = new_index

    points = np.delete(points, 2, 1)
    for index in range(0, len(face_indexes)):
        face_nodes = mesh2d.faces[face_indexes[index]]  # get the nodes index of the face
        node0_index = face_nodes[0]
        node1_index = face_nodes[1]
        node2_index = face_nodes[2]
        node0coordinates = mesh2d.vertices[node0_index]  # get cartesian coordinates of node0
        node1coordinates = mesh2d.vertices[node1_index]  # get cartesian coordinates of node1
        node2coordinates = mesh2d.vertices[node2_index]  # get cartesian coordinates of node2
        # Barycentric coordinates are invariants under plane-projections
        node0coordinates = node0coordinates[:-1]  # remove last component
        node1coordinates = node1coordinates[:-1]  # remove last component
        node2coordinates = node2coordinates[:-1]  # remove last component
        bar_coord = getBarycentricCoord(points[c], node0coordinates, node1coordinates, node2coordinates)
        v0 = nodes_values[node0_index]  # get the associated value to the node0
        v1 = nodes_values[node1_index]  # get the associated value to the node1
        v2 = nodes_values[node2_index]  # get the associated value to the node2
        interpolated_value = bar_coord[0] * v0 + bar_coord[1] * v1 + bar_coord[2] * v2
        interpolated_values.append(interpolated_value)
        c += 1
    interpolated_values = np.array(interpolated_values)
    return interpolated_values


def generate_grd(mesh2d, nodes_values, xres, yres, sw, ne, foutput):
    """
    This function generates a grd structured grid from the mesh2d

    :param mesh2d: trimesh object of a mesh projected to z=0
    :param nodes_values: array of node values of the mesh2d that will be used to assign the final values
    :param xres: x resolution of the out mesh
    :param yres: y resolution of the out mesh
    :param sw: lower left corner of the out mesh
    :param ne: upper right corner of the out mesh
    :param foutput: name of the output file
    :return: netCDF grid
    """
    x = np.arange(sw[0], ne[0], xres)  # partition in x
    y = np.arange(sw[1], ne[1], yres)  # partition in y

    Nrow = len(y)
    Ncolumn = len(x)

    points = np.array(list(itertools.product(x, y)))     # Points of the grd to be interpolated
    points = np.c_[points, (-1) * np.ones(len(points))]  # add z=-1 to each point to keep working on 3D

    interpolated_values = interpolate_pointCloud(points, mesh2d, nodes_values)  # interpolate the values
    interpolated_values = interpolated_values.reshape(Ncolumn, Nrow).T
    grdwrite(x, y, interpolated_values, foutput)  # ggenerate the final mesh
    return


def wgs_boundaries(sw, ne, inputcrs):
    """
    Transform SW and NE corners of a mesh to their corresponding coordinates in WGS84

    :param sw: lower left corner of the input mesh
    :param ne: upper right corner of the input mesh
    :param inputcrs: CRS of the SW, NE points
    :return: the four new corners: lowe left (LL), upper left (UL),
                                        lower right (LR), upper right (UR)
    """
    xmin = sw[0]
    xmax = ne[0]
    ymin = sw[1]
    ymax = ne[1]

    transformer = Transformer.from_crs(inputcrs, "epsg:4326", always_xy=True)
    xLL, yLL = transformer.transform(xmin, ymin)
    xUL, yUL = transformer.transform(xmin, ymax)
    xLR, yLR = transformer.transform(xmax, ymin)
    xUR, yUR = transformer.transform(xmax, ymax)

    LL = [xLL, yLL]
    UL = [xUL, yUL]

    LR = [xLR, yLR]
    UR = [xUR, yUR]

    return LL, UL, LR, UR


def hysea_mesh_corners(mesh2d, inputcrs):
    """
    This function takes the corners of the input mesh (mesh2d) and return the optimal SW, NE corners
    for the transformed mesh in WGS84 coordinates

    :param mesh2d: trimesh object of a mesh projected to z=0
    :param inputcrs: CRS of the mesh2d
    :return: two list SW, NE
    """
    sw = mesh2d.bounds[0][:2]  # Lower left corner
    ne = mesh2d.bounds[1][:2]  # Upper right corner

    transformer = Transformer.from_crs(inputcrs, "epsg:4326", always_xy=True)

    x = np.arange(sw[0], ne[0], 1)
    y = np.arange(sw[1], ne[1], 1)

    y_lowerRow = np.repeat(sw[1], len(x))
    xnew, ynew = transformer.transform(x, y_lowerRow)
    ymin = max(ynew)

    y_upperRow = np.repeat(ne[1], len(x))
    xnew, ynew = transformer.transform(x, y_upperRow)
    ymax = min(ynew)

    x_leftColumn = np.repeat(sw[0], len(y))
    xnew, ynew = transformer.transform(x_leftColumn, y)
    xmin = max(xnew)

    x_rightColumn = np.repeat(ne[0], len(y))
    xnew, ynew = transformer.transform(x_rightColumn, y)
    xmax = min(xnew)

    SW_new = [xmin, ymin]
    NE_new = [xmax, ymax]

    return SW_new, NE_new


def get_values_inside_rectangle(x, y, sw, ne):
    """
    This function takes two 1D arrays x and y and corners SW, NE, and returns a
    subset of x and y that are within the provided corners

    :param x: 1D array of x coordinates
    :param y: 1D array of y coordinates
    :param sw: SW corner
    :param ne: NE corner
    :return: subsets of x and y inside the limits established by SW and NE
    """
    indexMin = bisect.bisect_left(x, sw[0])  # retrieve index of first element greater than sw[0]
    indexMax = bisect.bisect_left(x, ne[0])
    x = x[indexMin:indexMax]
    indexMin = bisect.bisect_left(y, sw[1])  # retrieve index of first element greater than sw[1]
    indexMax = bisect.bisect_left(y, ne[1])
    y = y[indexMin:indexMax]
    return x, y


def generate_bathymetry(path2SeissolOutput, seissolevent_crs, outx_resolution, outy_resolution, outfile):
    """
    This function generates a topobathymetry file using the seissol output nodes values

    :param path2SeissolOutput: path to the file .xdmf generated by SeisSol. Same folder must contain
                                the files of the vertex and cell information
    :param seissolevent_crs: CRS of the seissol output
    :param outx_resolution: x resolution of the out mesh
    :param outy_resolution: y resolution of the out mesh
    :param outfile: name of the output file
    :return: structured bathymetry grid generated using seissol nodes
    """
    mesh3d = generateMesh3DfromSeissol(path2SeissolOutput)
    bathy = mesh3d.vertices[:, 2]
    mesh2d = generateMesh2DfromSeissol(path2SeissolOutput)
    mesh2d_wgs = mesh2dCRSconversion(mesh2d, seissolevent_crs)
    SW, NE = hysea_mesh_corners(mesh2d, seissolevent_crs)
    generate_grd(mesh2d_wgs, bathy, outx_resolution, outy_resolution, SW, NE, outfile)
    return


def seissol2hysea(path2SeissolOutput, seissolevent_crs, outnetcdf, instants=[], outx_resolution=None,
                        outy_resolution=None, only_vertical=False, raster_file=None, points_given=None):
    """
    This function convert the Seissol model output to a structured mesh in netcdf format. The resulting netCDF
    contains information about the displacements u1,u2,u3 on each time step. The order of kwargs arguments is: first
    look for "points_given", if not look for the "raster_file", if not look for the "outx_resolution "and
    "outy_resolution"

    :param path2SeissolOutput: path to seissol output
    :param seissolevent_crs: crs of the seissol mesh
    :param outnetcdf: name of the resulting netcdf
    outx_resolution and outy_resolution must be provided if raster_file and points_given are no provided!
    :param instants: time steps to include in the out netCDF. If not provided, all time steps will be included
    :param outx_resolution: x resolution for the nc file (decimal degress)
    :param outy_resolution: y resolution for the nc file (decimal degress)
    :param only_vertical: if true, only vertical displacements u3 are generated in the netCDF
    :param raster_file: if provided, points location will be used to generate the netCDF (formats are .nc, .tif, .grd)
    :param points_given: if provided, points location will be used to generate the netCDF. It is a list [x,y],
    where x,y are ndarrays of the longitude and latitude coordinates, resp.

    :return: netCDF file
    """
    sx = seissolxdmf.seissolxdmf(path2SeissolOutput)  # open the SeisSol file
    ndt = sx.ReadNdt()  # number of time steps in the Seissol file
    if not instants:
        # if not specific instant provided, use all in the seissol output
        instants = range(0, ndt)
    else:
        # check if instants provided are within the possible ones
        if not all(x in range(0, ndt) for x in instants):
            print("Instants provided are outside the range of timesteps in SeisSol's output")

    if only_vertical:
        variables = ["u3"]
    else:
        variables = ["u1", "u2", "u3"]

    # First we need the arrays containing the interpolation associated to the nodes
    if not os.path.exists("nodes_arrays"):
        os.mkdir("nodes_arrays")

    nodes2generate = []

    for (var, t) in list(itertools.product(variables, instants)):
        # check if nodes arrays already exists
        name = "node_values_{}_timestep{}.npy".format(var, t)
        if not os.path.exists(os.path.join("nodes_arrays", name)):
            nodes2generate.append((var, t))

    if nodes2generate:
        # Generate the arrays containing the variables values assigned to the nodes in case they don't exist
        mesh3d = generateMesh3DfromSeissol(path2SeissolOutput)
        for (var, t) in nodes2generate:
            print("generating array of nodes values for {}-timestep {}".format(var, t))
            assign_nodes_values(path2SeissolOutput, mesh3d, var, t)
        print("All nodes values arrays have been generated successfully")
    else:
        print("All nodes values arrays already exist")

    mesh2d = generateMesh2DfromSeissol(path2SeissolOutput)      # generate the 2d mesh object
    mesh2d_wgs = mesh2dCRSconversion(mesh2d, seissolevent_crs)  # create new 2d mesh with nodes CRS in WGS84

    SW, NE = hysea_mesh_corners(mesh2d, seissolevent_crs)  # Optimal corners of the resulting mesh
    # Now define the structured mesh for HySEA
    if points_given is not None:
        print("points arrays given")
        # Set of points provided by the user
        x = points_given[0]
        y = points_given[1]
        x, y = get_values_inside_rectangle(x, y, SW, NE)    # get the subset inside the optimal corners
    elif raster_file is not None:
        print("raster file provided")
        # Set of points provided by the user in the raster file
        extension = raster_file.split(".")[-1]
        if extension in ["nc", "grd"]:
            ds = Dataset(raster_file)
            var_names = list(ds.variables.keys())
            xaxis = ["lon", "x", "longitude"]
            yaxis = ["lat", "y", "latitude"]
            for namex in var_names:
                if namex in xaxis:
                    x = ds[namex][:]
            for namey in var_names:
                if namey in yaxis:
                    y = ds[namey][:]
            x, y = get_values_inside_rectangle(x, y, SW, NE)    # get the subset inside the optimal corners
            ds.close()
        elif extension == "tif":
            ds = rasterio.open(raster_file)
            band1 = ds.read(1)
            height = band1.shape[0]
            width = band1.shape[1]
            cols, rows = np.meshgrid(np.arange(width), np.arange(height))
            xs, ys = rasterio.transform.xy(ds.transform, rows, cols)
            x = np.array(xs[0])
            y = np.array(ys)[::-1][:, 0]
            x, y = get_values_inside_rectangle(x, y, SW, NE)    # get the subset inside the optimal corners
            ds.close()
        else:
            print("Raster file format not recognized. It should be .nc, .grd or .tif")

    else:
        # Set of points that best fit within the triangular mesh. Resolutions provided by the user.
        print("None set of points provided. Using the optimal ones")
        print("outx_resolution and outy_resolution must have been provided")
        x = np.arange(SW[0], NE[0], outx_resolution)  # partition in x
        y = np.arange(SW[1], NE[1], outy_resolution)  # partition in y

    Nrow = len(y)
    Ncolumn = len(x)
    points = np.array(list(itertools.product(x, y)))        # Points of the grd to be interpolated
    points = np.c_[points, (-1) * np.ones(len(points))]     # add z=-1 to each point to keep working on 3D

    # Now create the netCDF file and fill it
    ds = Dataset(outnetcdf, 'w', format='NETCDF4')
    ds.title = "SeisSol model outputs converted from triangular mesh to structured mesh by interpolation"
    ds.history = "File written using netCDF4 Python module"
    today = datetime.today()
    ds.description = "Created " + today.strftime("%d/%m/%y")
    time = ds.createDimension('time', None)
    lat = ds.createDimension('y', Nrow)
    lon = ds.createDimension('x', Ncolumn)
    times = ds.createVariable('time', 'f4', ('time',))
    longitude = ds.createVariable('x', 'f8', ('x',))
    latitude = ds.createVariable('y', 'f8', ('y',))
    longitude.units = "degrees east (WGS84)"
    latitude.units = "degrees north (WGS84)"
    times.units = "time step"
    longitude[:] = x
    latitude[:] = y

    if only_vertical:
        u3 = ds.createVariable('u3', 'f8', ('time', 'y', 'x'))
        u3.units = "meters"
        for t in instants:
            print("including variable u3-timestep{} in netCDF".format(t))
            array = os.path.join("nodes_arrays", "node_values_u3_timestep{}.npy".format(t))
            nodes_values = np.load(array)
            interpolated_values = interpolate_pointCloud(points, mesh2d_wgs, nodes_values)
            interpolated_values = interpolated_values.reshape(Ncolumn, Nrow).T
            u3[t, :, :] = interpolated_values
    else:
        u1 = ds.createVariable('u1', 'f8', ('time', 'y', 'x'))
        u2 = ds.createVariable('u2', 'f8', ('time', 'y', 'x'))
        u3 = ds.createVariable('u3', 'f8', ('time', 'y', 'x'))
        u1.units = "meters"
        u2.units = "meters"
        u3.units = "meters"
        dic = {"u1": u1, "u2": u2, "u3": u3}
        for t in instants:
            for variable in variables:
                print("including variable {}-timestep{} in netCDF".format(variable, t))
                array = os.path.join("nodes_arrays", "node_values_{}_timestep{}.npy".format(variable, t))
                nodes_values = np.load(array)
                interpolated_values = interpolate_pointCloud(points, mesh2d_wgs, nodes_values)
                interpolated_values = interpolated_values.reshape(Ncolumn, Nrow).T
                dic[variable][t, :, :] = interpolated_values

    ds.close()
    return


# Examples
path = r"C:\Users\Alex\PycharmProjects\curso_python\seissol_files\hdf5_float"
file = "Fra_v4_noWL_hdf5_float_2.5s_50s-surface.xdmf"
path2SeissolOutput = os.path.join(path, file)  # path to SeisSol file
inputcrs = "+proj=tmerc +datum=WGS84 +k=0.9996 +lon_0=26.25 +lat_0=37.75"  # CRS of the input 2d mesh


# 1) Without points_given and without raster_file. All instants and all displacements u1, u2, u3
xres_meters = 250  # desired x resolution in meters for the nc file
yres_meters = 250  # desired y resolution in meters for the nc file
xres_dd = xres_meters / (3600 * 30)  # rough conversion of x resolution to decimal degrees
yres_dd = yres_meters / (3600 * 30)  # rough conversion of y resolution to decimal degrees

#seissol2hysea(path2SeissolOutput, inputcrs, "test_seissolOutFloat.nc", outx_resolution=xres_dd, outy_resolution=yres_dd,
#                    only_vertical=False)

# 2) Providing a set of points. Only vertical displacement u3 and instants 1 and 4
#x = np.arange(25, 28, 0.004)
#y = np.arange(31, 33, 0.004)
#
#seissol2hysea(path2SeissolOutput, inputcrs, "test_seissolOutFloat.nc", only_vertical=True, instants=[1, 4],
#              points_given=[x, y])


# 3) Providing a set of points from a raster file. Only vertical displacement u3 and all instants
#seissol2hysea(path2SeissolOutput, inputcrs, "test_seissolOutFloat.nc", only_vertical=True,
#              raster_file="gebco450m.tif")









#generate_bathymetry(path2SeissolOutput, inputcrs, xres_dd, yres_dd, "seissol_bathy250m.grd")



"""PARA PINTAR"""
## Esto reescalada la malla para meterla en un cubo
# mesh=mesh2d
# rescale = max(mesh.extents) / 2.
# tform = [-(mesh.bounds[1][i] + mesh.bounds[0][i]) / 2. for i in range(3)]
# matrix = np.eye(4)
# matrix[:3, 3] = tform
# mesh.apply_transform(matrix)
# matrix = np.eye(4)
# matrix[:3, :3] /= rescale
# mesh.apply_transform(matrix)
#
# Esto renderiza la escena
# scene = trimesh.Scene([mesh])
# viewer = trimesh.viewer.windowed.SceneViewer(scene, flags='wireframe')


"""PARA EXPORTAR UNA MALLA"""
# mesh = generateMesh2DfromSeissol(file)
# mesh.export('new_mesh.stl')


























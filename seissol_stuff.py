import seissolxdmf





fn_hdf5_float = 'seissol_files/hdf5_float/Fra_v4_noWL_hdf5_float_2.5s_50s-surface.xdmf'
fn_hdf5_single = 'seissol_files/hdf5_single/Fra_v4_WL_hdf5_single_WL_50s-surface.xdmf'
fn_binary_double = 'seissol_files/raw_double/Fra_v4_noWL_raw_double_25s_50s-surface.xdmf'


# initiate class
sx = seissolxdmf.seissolxdmf(fn_hdf5_single)
#print(sx.tree)


print("\n")
print("El fichero base es: {}".format(fn_hdf5_single.split("/")[-1]))
print("Los campos disponibles en el fichero son: ")
print(sx.ReadAvailableDataFields())
variable = "locationFlag"


# Number of cells
nElements = sx.ReadNElements()
print("Number of cells: {}".format(nElements))

# Read time step
dt = sx.ReadTimeStep()
print("Time step: {}".format(dt))

# Read number of time steps
ndt = sx.ReadNdt()
print("Number of time steps: {} \n".format(ndt))

# Load geometry array as a numpy array of shape ((nodes, 3))
# Esto requiere el fichero que acaba en "surface_vertex"
geom = sx.ReadGeometry()
print("Array de la geometria: (requiere el fichero surface_vertex.h5)")
print("-Hay {} nodos".format(len(geom)))
print("-Los primeros 5 nodos son: ")
print(geom[0])
print(geom[1])
print(geom[2])
print(geom[3])
print(geom[4])


# Load connectivity array as a numpy array of shape ((nElements, 3 or 4))
# The connectivity array gives for each cell a list of vertex ids.
# Esto requiere el fichero que termina en "surface_cell"
print("\nArray de la conectividad: (requiere el fichero surface_cell.h5)")
print("-Cada elemento es una celda y los valores indican los vertices a los que esta conectada")
print("-Las primeras 5 celdas tiene estas conectividades: ")
connect = sx.ReadConnect()
print(connect[0])
print(connect[1])
print(connect[2])
print(connect[3])
print(connect[4])
print("(puede ocurrir que una celda tenga 4 vertices) \n")


# Check, whether variable "SRs" exists in the SeisSol output
#assert "SRs" in sx.ReadAvailableDataFields()

# load v1s as a numpy array of shape ((ndt, nElements))
print("Leemos la variable {}".format(variable))
print("Esto es un array de todas las celdas, donde cada celda \ntiene {} arrays, uno por instante de tiempo".format(ndt))
v1s = sx.ReadData(variable)
print("La variable {} tiene estos valores:".format(variable))
print(v1s)
print(len(v1s))
print(len(v1s[0]))

# load the 8th time ste of the v1s array as a numpy array of shape (nElements)
print("\n")
print("Podemos extraer todos los valores en un instante de tiempo concreto.")
print("Los valores de {} en el timestep={} son:".format(variable,ndt))
v1s_t = sx.ReadData(variable, ndt-1)
print(v1s_t)



"""AHORA TRASTEAMOS CON LOS DATOS"""
#print("\n")
#print("Trasteo con los datos")
#print(geom)
#xs=[]
#ys=[]
#zs=[]
#for i in range (0,len(geom)):
#    xs.append(geom[i][0])
#    ys.append(geom[i][1])
#    zs.append(geom[i][2])
#
#xmin=min(xs)
#xmax=max(xs)
#ymin=min(ys)
#ymax=max(ys)
#zmin=min(zs)
#zmax=max(zs)
#
#print(xmin)
#print(xmax)
#print(ymin)
#print(ymax)
#print(zmin)
#print(zmax)











import numpy as np
import plotly.graph_objects as go
import open3d as o3d


def visualize_inspections(inspection_a, inspection_b):
    figure = go.Figure()

    add_geometry(figure, inspection_a, "Inspection A", "royalblue")
    add_geometry(figure, inspection_b, "Inspection B", "darkorange")

    figure.update_layout(
        scene=dict(
            xaxis_title="X (m)",
            yaxis_title="Y (m)",
            zaxis_title="Z (m)",
            aspectmode="data",
        ),
    )

    figure.show()


def add_geometry(figure, geometry, name, color):
    if isinstance(geometry, o3d.geometry.PointCloud):
        points = np.asarray(geometry.points)

        figure.add_trace(
            go.Scatter3d(
                x=points[:, 0],
                y=points[:, 1],
                z=points[:, 2],
                mode="markers",
                marker=dict(size=3, color=color),
                name=name,
            )
        )

    elif isinstance(geometry, o3d.geometry.TriangleMesh):
        vertices = np.asarray(geometry.vertices)
        triangles = np.asarray(geometry.triangles)

        figure.add_trace(
            go.Mesh3d(
                x=vertices[:, 0],
                y=vertices[:, 1],
                z=vertices[:, 2],
                i=triangles[:, 0],
                j=triangles[:, 1],
                k=triangles[:, 2],
                color=color,
                opacity=0.65,
                name=name,
            )
        )

    else:
        raise TypeError(f"Unsupported geometry type: {type(geometry)}")

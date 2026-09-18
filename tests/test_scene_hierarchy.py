import os
import pytest

from src.core.config import Config
from src.core.database import UmaDatabase
from src.core.unity import UnityLogic


def test_scene_hierarchy_nonexistent_file():
    """Verify that nonexistent or invalid files return empty tuple and do not crash."""
    result = UnityLogic.get_scene_hierarchy("/nonexistent/file/path")
    assert result == ()


def test_scene_hierarchy_structure_and_performance():
    """Verify scene hierarchy extraction on real Uma game assets if available."""
    Config.load()
    data_root = Config.get_data_root()
    if not data_root or not os.path.isdir(data_root):
        pytest.skip("Game data root not configured or directory does not exist.")

    try:
        db = UmaDatabase()
    except Exception as e:
        pytest.skip(f"Could not open UmaDatabase: {e}")

    row = db.conn.cursor().execute(
        'SELECT a.i, a.n, a.h FROM a WHERE a.n LIKE "3d/env/%/pfb_%" LIMIT 1'
    ).fetchone()

    if not row:
        row = db.conn.cursor().execute(
            'SELECT a.i, a.n, a.h FROM a WHERE a.n LIKE "3d/env/%" LIMIT 1'
        ).fetchone()

    if not row:
        pytest.skip("No 3d/env assets found in database.")

    asset_id, logical_name, f_hash = row
    phys_path = os.path.join(data_root, f_hash[:2], f_hash)
    if not os.path.exists(phys_path):
        pytest.skip(f"Asset file {phys_path} not found locally.")

    bundle_key = db.get_key_by_hash(f_hash)
    UnityLogic.set_key_provider(db.get_key_by_hash)

    tree = UnityLogic.get_scene_hierarchy(phys_path, bundle_key=bundle_key)
    assert isinstance(tree, tuple)

    if len(tree) > 0:
        root = tree[0]
        assert "name" in root
        assert "go_path_id" in root
        assert "tf_path_id" in root
        assert "components" in root
        assert "children" in root
        assert "local_pos" in root
        assert "local_rot" in root
        assert "local_scale" in root
        assert isinstance(root["children"], tuple)

        # Validate node count and tree traversal
        def count_nodes(node):
            return 1 + sum(count_nodes(c) for c in node["children"])

        total_nodes = sum(count_nodes(r) for r in tree)
        assert total_nodes >= len(tree)


def test_hierarchy_controller_render_tree_no_callback_error():
    """Verify that HierarchyController.render_tree builds DPG tree nodes without callback errors."""
    import dearpygui.dearpygui as dpg
    from src.ui.controllers.hierarchy_controller import HierarchyController

    class DummyApp:
        def __init__(self):
            self.current_asset_id = 1

    dpg.create_context()
    try:
        app = DummyApp()
        ctrl = HierarchyController(app)

        test_tree = (
            {
                "name": "RootNode",
                "go_path_id": 100,
                "tf_path_id": 101,
                "components": ("Transform", "Animator"),
                "mesh_name": None,
                "mesh_path_id": None,
                "materials": (),
                "local_pos": (0.0, 0.0, 0.0),
                "local_rot": (0.0, 0.0, 0.0, 1.0),
                "local_scale": (1.0, 1.0, 1.0),
                "children": (
                    {
                        "name": "ChildNode",
                        "go_path_id": 200,
                        "tf_path_id": 201,
                        "components": ("Transform", "MeshFilter", "MeshRenderer"),
                        "mesh_name": "TestMesh",
                        "mesh_path_id": 202,
                        "materials": ("Mat1",),
                        "local_pos": (1.0, 2.0, 3.0),
                        "local_rot": (0.0, 0.0, 0.0, 1.0),
                        "local_scale": (1.0, 1.0, 1.0),
                        "children": (),
                    },
                ),
            },
        )

        ctrl.current_tree_data["scene_"] = {
            "tree": test_tree,
            "phys_path": "/dummy/path",
            "bundle_key": None,
        }

        with dpg.window(tag="test_window"):
            dpg.add_child_window(tag="scene_ui_hierarchy_tree_parent")
            dpg.add_child_window(tag="scene_ui_hierarchy_inspector_parent")

        # This will render both parent and child nodes
        ctrl.render_tree("scene_")

        # Verify items were actually created in DPG
        children = dpg.get_item_children("scene_ui_hierarchy_tree_parent", slot=1)
        assert len(children) > 0

        # Simulate selecting the child node
        ctrl.on_node_selected(test_tree[0]["children"][0], "scene_")
        assert ctrl.selected_node["scene_"]["name"] == "ChildNode"

    finally:
        dpg.destroy_context()


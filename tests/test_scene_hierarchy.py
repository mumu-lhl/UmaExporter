import os
import shutil
import tempfile
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


def test_find_stage_related_prefabs():
    """Verify companion prefab discovery for live and race stages."""
    class FakeCursor:
        def __init__(self, query_results):
            self.query_results = query_results
        def execute(self, sql, params):
            return self
        def fetchall(self):
            return self.query_results

    class FakeDb:
        def __init__(self, results):
            self.conn = type("Conn", (), {"cursor": lambda s: FakeCursor(results)})()

    # Live stage test
    live_db = FakeDb([
        (1, "3d/env/live/live10101/pfb_env_live10101_main000", "HASH1"),
        (2, "3d/env/live/live10101/pfb_env_live10101_roof_truss", "HASH2"),
    ])
    group, prefabs = UnityLogic.find_stage_related_prefabs(
        "3d/env/live/live10101/pfb_env_live10101_main000", live_db
    )
    assert group == "live10101"
    assert len(prefabs) == 2

    # Race stage test
    race_db = FakeDb([
        (1, "3d/env/race/race00000/pfb_env_race00000_001", "HASH1"),
    ])
    group, prefabs = UnityLogic.find_stage_related_prefabs(
        "3d/env/race/race00000/pfb_env_race00000_001", race_db
    )
    assert group == "race00000"
    assert len(prefabs) == 1

    # Non-stage asset test
    group, prefabs = UnityLogic.find_stage_related_prefabs(
        "3d/chara/body/bdy0001_00/pfb_bdy0001_00", live_db
    )
    assert group is None
    assert prefabs == ()


def test_hierarchy_controller_stage_buttons_and_inspector_sync():
    """Verify that stage buttons toggle correctly and detached inspector syncs."""
    import dearpygui.dearpygui as dpg
    from src.ui.controllers.hierarchy_controller import HierarchyController

    class DummyApp:
        def __init__(self):
            self.current_asset_id = 10
            self.current_asset_data = {"id": 10, "name": "3d/env/live/live10101/pfb_env_live10101_main000"}
            self.db = None
            self.f3d_service = None

    dpg.create_context()
    try:
        app = DummyApp()
        ctrl = HierarchyController(app)

        with dpg.window(tag="test_window_stage"):
            dpg.add_group(tag="scene_ui_stage_banner", show=False)
            dpg.add_text(tag="scene_ui_stage_badge")
            dpg.add_button(tag="scene_ui_assemble_stage_btn", show=False)
            dpg.add_button(tag="scene_ui_preview_stage_fbx_btn", show=False)
            dpg.add_button(tag="scene_ui_export_stage_fbx_btn", show=False)
            dpg.add_child_window(tag="scene_ui_hierarchy_tree_parent")
            dpg.add_child_window(tag="scene_ui_hierarchy_inspector_parent")

        # Case 1: Multiple stage prefabs -> buttons should become visible
        fake_prefabs = (
            (1, "part1", "h1"),
            (2, "part2", "h2"),
        )
        ctrl._apply_hierarchy_result(
            "scene_",
            ctrl.request_ids["scene_"],
            10,
            "/dummy/phys",
            None,
            (),
            stage_group="live10101",
            stage_prefabs=fake_prefabs,
            logical_path="3d/env/live/live10101/pfb_env_live10101_main000",
        )

        assert dpg.is_item_shown("scene_ui_stage_banner") is True
        assert "live10101" in dpg.get_value("scene_ui_stage_badge")
        assert dpg.is_item_shown("scene_ui_assemble_stage_btn") is True
        assert dpg.is_item_shown("scene_ui_preview_stage_fbx_btn") is True
        assert dpg.is_item_shown("scene_ui_export_stage_fbx_btn") is True

        # Case 2: Detached window inspector synchronization
        with dpg.window(tag=ctrl.detached_window_tag):
            dpg.add_child_window(tag=f"{ctrl.detached_window_tag}_inspector_container")

        node = {
            "name": "LiveSpeaker",
            "go_path_id": 999,
            "tf_path_id": 998,
            "components": ("Transform",),
        }
        ctrl.on_node_selected(node, "scene_")

        # Ensure both regular and detached inspector containers received node content
        reg_children = dpg.get_item_children("scene_ui_hierarchy_inspector_parent", slot=1)
        det_children = dpg.get_item_children(f"{ctrl.detached_window_tag}_inspector_container", slot=1)
        assert len(reg_children) > 0
        assert len(det_children) > 0

    finally:
        dpg.destroy_context()


def test_export_assembled_stage_fbx_cache(monkeypatch, tmp_path):
    """Verify that export_assembled_stage_fbx caches and reuses results in preview mode."""
    class FakeDb:
        def get_key_by_hash(self, h):
            return None

    fake_db = FakeDb()
    called = []

    def fake_find(logical_path, db):
        return "live99999", [(1, "live99999_main", "hash1")]

    def fake_cli(paths, target_dir, mode="splitObjects", bundle_keys=None):
        called.append(target_dir)
        # Create a dummy FBX in target_dir
        with open(os.path.join(target_dir, "test.fbx"), "w") as f:
            f.write("FBX")

    monkeypatch.setattr(UnityLogic, "find_stage_all_bundles", fake_find)
    monkeypatch.setattr(UnityLogic, "_export_via_cli", fake_cli)
    stage_cache_dir = tmp_path / "stage_cache"
    stage_cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Config, "get_stage_cache_dir", lambda: str(stage_cache_dir))
    monkeypatch.setattr(Config, "get_data_root", lambda: str(tmp_path))

    # Create dummy physical file
    bundle_dir = tmp_path / "ha"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_file = bundle_dir / "hash1"
    bundle_file.write_text("bundle")

    # First call: should call CLI and save to stage_cache_dir
    res1 = UnityLogic.export_assembled_stage_fbx("3d/env/live/live99999", fake_db)
    assert len(called) == 1
    assert len(res1) == 1
    assert res1[0].endswith("test.fbx")
    assert str(stage_cache_dir) in res1[0]

    # Second call: should hit cache and NOT call CLI again
    res2 = UnityLogic.export_assembled_stage_fbx("3d/env/live/live99999", fake_db)
    assert len(called) == 1  # Not incremented
    assert res2 == res1

    # Test clearing cache
    freed = Config.clear_stage_cache()
    assert freed > 0
    assert not os.path.exists(res1[0])




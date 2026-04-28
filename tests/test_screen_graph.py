from core.autobuilder.screen_graph import ScreenGraph


def test_screen_graph_stores_screens_and_transitions():
    graph = ScreenGraph()
    graph.add_screen(
        screen_id="main_menu",
        screen_hash="abc",
        screen_type="menu",
        texts=["Play"],
        elements=["play_button"],
        safe_actions=["tap_play"],
    )
    graph.add_transition("main_menu", "tap_play", "gameplay")

    payload = graph.to_dict()
    restored = ScreenGraph.from_mapping(payload)

    assert restored.get("main-menu").type == "menu"
    assert restored.outgoing("main_menu")[0].to_screen == "gameplay"

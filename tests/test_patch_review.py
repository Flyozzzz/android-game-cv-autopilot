from core.autobuilder.patches import AutopilotPatch
from core.autobuilder.review import PatchReviewQueue


def test_patch_review_requires_explicit_decision_for_risky_patch(tmp_path):
    queue = PatchReviewQueue(tmp_path)
    review = queue.submit(AutopilotPatch(type="add_roi", payload={"roi": "popup"}, requires_review=True))

    assert review["status"] == "pending"
    decided = queue.decide(review["id"], approve=False, actor="tester")

    assert decided["status"] == "rejected"
    assert decided["audit"][-1]["actor"] == "tester"

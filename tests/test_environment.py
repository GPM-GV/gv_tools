from gv_tools.environment import dependency_report


def test_required_dependency_report_has_stable_fields():
    report = dependency_report(("required",))
    assert {item["package"] for item in report} == {"numpy", "pandas", "xarray"}
    assert all(set(item) == {
        "group", "package", "minimum", "installed", "available", "compatible"
    } for item in report)
    assert next(item for item in report if item["package"] == "numpy")["minimum"] == "1.24"
    assert all(item["compatible"] for item in report)

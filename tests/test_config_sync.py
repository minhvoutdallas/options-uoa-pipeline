"""Guard against config drift: the UOA thresholds live in config/pipeline.yml
(read by ingestion) and are mirrored as vars in dbt/dbt_project.yml (read by
the models). This test fails if the two ever disagree."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dbt_vars_match_pipeline_config():
    pipeline = yaml.safe_load((ROOT / "config" / "pipeline.yml").read_text(encoding="utf-8"))
    dbt_project = yaml.safe_load((ROOT / "dbt" / "dbt_project.yml").read_text(encoding="utf-8"))

    uoa = pipeline["uoa"]
    dbt_vars = dbt_project["vars"]

    assert dbt_vars["ntm_pct"] == uoa["ntm_pct"]
    assert dbt_vars["uoa_baseline_days"] == uoa["baseline_days"]
    assert dbt_vars["uoa_volume_multiple"] == uoa["volume_multiple"]

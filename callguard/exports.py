"""File exports offered from the UI."""

import pandas as pd


CSV_COLUMNS = ("Agent_name", "agent_id", "Avg score")


def agent_scores_csv(df) -> bytes:
    """Agent name, agent ID and average QA score as CSV bytes."""
    out = pd.DataFrame({
        "Agent_name": df["agent_name"] if "agent_name" in df else [],
        "agent_id": df["agent_id"] if "agent_id" in df else [],
        "Avg score": (df["avg_score"].round(2) if "avg_score" in df else []),
    }, columns=list(CSV_COLUMNS))
    # utf-8-sig so Excel opens accented names correctly on a double-click.
    return out.to_csv(index=False).encode("utf-8-sig")

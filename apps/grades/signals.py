"""Signals — grade saves do NOT auto-publish; GPA recomputes only after batch.publish()."""
# GPA recompute is triggered explicitly in GradeBatch.publish() → _trigger_gpa_recompute()
# No automatic signal needed here, keeping the flow intentional and controlled.

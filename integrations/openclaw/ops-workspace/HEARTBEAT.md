<!-- Heartbeat template; comments-only content prevents scheduled heartbeat API calls. -->

# Keep this file empty (or with only comments) to skip heartbeat API calls.

# Optional (administrator decision — costs model calls): uncomment to have the
# agent review open incidents on each heartbeat and summarize only changes.
# - Call marketflow_ops__get_control_center_summary. If counts.open_incidents is
#   0 and monitor.status is ok, reply HEARTBEAT_OK and nothing else.

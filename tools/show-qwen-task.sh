/home/mt/Proj/localai/tools/local-ai-bridge/run-local-ai-task list --state running
/home/mt/Proj/localai/tools/local-ai-bridge/run-local-ai-task status <task_id>

# 生のイベント（Qwen がどのツールを何回呼んだか。tool_use の行を数える）
ls -t /home/mt/.local/state/local-ai-bridge/tasks/ | head -1     # 最新の task_id
T=/home/mt/.local/state/local-ai-bridge/tasks/<task_id>
tail -3 "$T/runner.log"
grep -c '"type":"tool_use"' "$T"/events-implement-0.jsonl
ls "$T"          # events-review-*.jsonl が出ていればレビュー段階、result.json が出れば完了


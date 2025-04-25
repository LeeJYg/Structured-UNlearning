import os
import json
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

sql_dir = "/home/jylee/SUN/job_queries"
jsonl_path = "/home/jylee/SUN/job_results/NL_queries/main_qa.jsonl"

console = Console()

def extract_number(filename):
    try:
        return int(filename.replace(".sql", ""))
    except ValueError:
        return float("inf")

sql_files = sorted(
    [f for f in os.listdir(sql_dir) if f.endswith(".sql") and not f.startswith("job_subqueries.")],
    key=extract_number
)

with open(jsonl_path, "r", encoding="utf-8") as f:
    nl_data = [json.loads(line) for line in f]

if len(sql_files) != len(nl_data):
    console.print(f"[bold red]⚠️ SQL 파일과 NL 질문 개수가 다릅니다! ({len(sql_files)} vs {len(nl_data)})[/bold red]")
else:
    for idx, (sql_file, nl_item) in enumerate(zip(sql_files, nl_data)):
        with open(os.path.join(sql_dir, sql_file), "r", encoding="utf-8") as f:
            sql_query = f.read().strip()

        nl_question = nl_item.get("question", "[No question found]")

        sql_text = Text(sql_query, style="bold cyan")
        nl_text = Text(nl_question, style="bold green")

        console.rule(f"[bold blue] Query #{idx}: {sql_file}")
        console.print(Panel(sql_text, title="🧾 SQL Query", border_style="cyan"))
        console.print(Panel(nl_text, title="💬 Natural Language Question", border_style="green"))

        input("\n👉 Enter를 누르면 다음 쿼리를 봅니다...\n")
SCHEMA_EXTRACTION_PROMPT = """You are a database schema designer. You are given a set of QA pairs that ask questions about authors and their associated attributes (e.g., birthplace, gender, literary genre, awards, influences, etc.).

Your goal is to design a SQL schema to store this information efficiently for use in a downstream QA system.

### Constraints:
- All provided QA pairs should be answerable using the resulting schema via SQL queries.
- The QA pairs are grouped in batches of 20, where each batch refers to a single author. Therefore, the schema should support extracting structured information *per author* from these 20 QA pairs.
- Each table must correspond to a meaningful **entity set**, such as `author`, `book`, `award`, etc.
- To represent relationships between entities (e.g., author and awards), you must use **join tables** (e.g., `author_award`) with appropriate foreign key references.
- Each entity table must include a **primary key**, and ID columns must be defined explicitly (e.g., `author_id INTEGER PRIMARY KEY`) without using AUTOINCREMENT or database-managed sequences.
- All SQL statements must be **valid and executable in DuckDB**.
- Use only standard SQL features supported by DuckDB (e.g., avoid `ON CONFLICT`, `AUTOINCREMENT`, etc.).

### Input QA pairs:
{samples}

Use only standard SQL and ensure the schema is compatible with DuckDB.
Begin with CREATE TABLE statements.

**Your output must only include valid SQL statements. Do not generate any explanatory text or commentary.**
"""

SCHEMA_MERGE_PROMPT = """You are an expert SQL schema designer refining and extending an existing database schema.

You are given:
1. A **current schema** composed of SQL CREATE TABLE statements.
2. A **new batch of QA pairs**, all referring to a single author.

Your task is to:
- Extend or revise the schema so that all new QA pairs can be represented using SQL queries over the resulting schema.
- Modify existing tables only if necessary. Otherwise, add new tables or join tables to accommodate new information.

### Constraints:
- Preserve and reuse existing entity sets and join tables when possible (e.g., if `award` or `book` table already exists, extend them rather than creating duplicates).
- Follow the same design principles as before:
  - Entity tables must represent meaningful concepts (e.g., author, award, book).
  - Use join tables for many-to-many relationships.
  - ID fields must be explicitly defined using `INTEGER PRIMARY KEY`, without AUTOINCREMENT.
- All SQL statements must be DuckDB-compatible.
- Ensure schema correctness and avoid redundant or conflicting definitions.

### Current schema:
{current_schema}

### New QA pairs:
{samples}

Update the schema by generating valid SQL CREATE TABLE statements.
Do not include explanatory text—only output valid SQL.
"""

UPSERT_EXTRACTION_PROMPT = """You are provided with the following SQL schema:

{schema}

Now, given the QA pairs below for a single author:

{qa_block}

Currently available info_type is {info_type_list}. (If you need to create a new info_type, you can do so.)

Generate one or more SQL statements (INSERT INTO and/or UPDATE) that populate the tables accordingly using the schema above. Ensure the statements are syntactically valid for DuckDB and consistent with the table definitions provided.

### Constraints:
- Use the provided author_id and info_id numbers sequentially.
- When inserting into the 'author' table, first check if the author already exists by matching 'full_name'.
- If the author exists, update only NULL fields. If not, insert the author.
- For 'info' and 'author_info', assign info_id sequentially starting from the given info_id.
- Use WHERE NOT EXISTS clauses instead of ON CONFLICT, since DuckDB does not support ON CONFLICT.
- When inserting multiple rows into 'author_info', you must generate a separate INSERT INTO ... SELECT ... WHERE NOT EXISTS statement for each row. Do not use a single INSERT INTO ... VALUES (...), (...).
- Only output pure SQL statements without any comments or explanations.
"""

FIRST_SUB_DATA_PROMPT = """You are given structured tabular data about an author and their associated factual information.

Your task is to convert the provided structured data into a natural and readable paragraph.

{data}

### Instructions:
- **Preserve all information from the structured data exactly. Do not omit anything.**
- **The resulting text must allow for the original tuples to be recovered.**
- **Format lists compactly and naturally.**
- **Do NOT use external knowledge or assumptions.**
- Ensure fluent and logically connected sentences.

Write a concise and fully detailed paragraph representing the data."""

FOLLOWUP_SUB_DATA_PROMPT = """You are given additional structured data about the same author.

### Previous paragraph:
{previous_summary}

### New data:
{new_data}

### Instructions:
- **Incorporate the new data into the existing paragraph naturally.**
- **Do not omit any detail.**
- **Do not use external information.**
- Maintain readability and paragraph structure.

Return an updated paragraph with all facts merged.
"""

SQL_TO_NL_PROMPT = """
You are an expert at converting SQL queries into natural language questions and answers.
Your task is to:
1. Rewrite the given SQL query into a clear, natural-sounding question that includes all the information necessary to reconstruct the original SQL query.
2. Provide the corresponding answer using the provided result.

Focus on:
- Making the question sound natural and conversational.
- Ensure the question includes all filters and conditions from the SQL query so that it can be precisely reconstructed.
- Keeping it clear and concise.
- Using the provided answer to generate a realistic response.

Example:
SQL: SELECT name 
FROM movies 
WHERE year = 1994 
    AND genre = 'Drama' 
    AND rating > 8.5;
Answer: The Shawshank Redemption
Natural Language:
Q: "Which drama movies released in 1994 have a rating higher than 8.5?"
A: "One example is The Shawshank Redemption."

Here is the SQL query:
{sql_query}

Answer:
{answer}

Now, rewrite this SQL query into a natural-sounding Q&A format.
"""

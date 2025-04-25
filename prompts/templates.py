FIRST_SUB_DATA_PROMPT = """You are given structured IMDb data from the {category} section, corresponding to the {kind} titled "{title}".

Following the instruction strictly, convert the following structured IMDb data into a natural and readable paragraph.

{data}

### Instructions:
- **Extract and include every piece of information from the structured data exactly as provided. No information should be omitted.**
- **The resulting text must allow for the original tuples to be recovered exactly as they appeared in the structured data.**
- **Use compact phrasing and avoid redundant details.**
- **Lists must be fully preserved, but formatted efficiently to improve readability.**
- **Do NOT use any external knowledge or prior information. Only use the provided data to generate the text.**
- **If a fact is not explicitly stated in the given data, do NOT infer, assume, or generate speculative content.**
- Ensure smooth logical flow between sentences.

Write a **compact and highly detailed** paragraph summarizing the above information."""

FOLLOWUP_SUB_DATA_PROMPT = """You are an expert writer. You are working on describing the {kind} titled "{title}".

### Context (Previously Processed Information):
{previous_summary}

### New Data:
{new_data}

### Instructions:
- **The new data is directly related to the previous information. Integrate it smoothly while preserving all details.**
- **The resulting text must allow for the original tuples to be recovered exactly as they appeared in the structured data.**
- **Do not omit or summarize any information. Every detail is important.**
- **Lists must be fully preserved, with all items included.**
- **Do NOT use any external knowledge or prior information. Only use the provided data to generate the text.**
- Use natural sentence structures instead of listing facts mechanically.
- Ensure smooth logical flow between sentences.
- Do **not** introduce any new or speculative information.

Write a well-structured, detailed paragraph that seamlessly incorporates the new data into the existing context."""

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


# FINAL_PROMPT = f"""Here is the extracted information about the movie "{movie_title}" from IMDb:

# {sub_texts["basic_info"]}

# {sub_texts["cast_info"]}

# {sub_texts["company_info"]}

# {sub_texts["keyword_info"]}

# {sub_texts["alternate_titles"]}

# {sub_texts["movie_links"]}

# {sub_texts["complete_cast"]}

# ### Task:
# - Combine the above details into a **cohesive, well-structured paragraph**.
# - Ensure **logical flow** and use **natural transitions** between sections.
# - Avoid redundancy and make the text **engaging and informative**.
# - Maintain a **neutral yet professional tone**, suitable for an IMDb-like description.

# Please generate a **single, well-formed paragraph** summarizing the details naturally.
#     """
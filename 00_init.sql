CREATE TABLE author (
    author_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    birth_date DATE,
    birth_place TEXT,
    lgbtq BOOLEAN,
    main_genre TEXT,
    current_residence TEXT
);

CREATE TABLE info (
    info_id INTEGER PRIMARY KEY,
    info_type TEXT NOT NULL
);

CREATE TABLE author_info (
    author_id INTEGER,
    info_id INTEGER,
    note TEXT,
    PRIMARY KEY (author_id, info_id),
    FOREIGN KEY (author_id) REFERENCES author(author_id),
    FOREIGN KEY (info_id) REFERENCES info(info_id)
);

\i /docker-entrypoint-initdb.d/all_queries.sql
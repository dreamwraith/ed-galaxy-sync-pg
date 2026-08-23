"""Database schema orchestration, DDL deployment, and maintenance for ed-galaxy-sync-pg.

Provides modular SQL script discovery and sequential application for PostgreSQL
schema setup, including extensions, domain tables, indexes, constraints,
analytic helper functions, and stored procedures for canonical normalization
and Dead-Letter Queue reprocessing.
"""

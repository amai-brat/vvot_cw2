import os

class Config:
  def __init__(self):
    self.ydb_endpoint = os.environ["YDB_ENDPOINT"]
    self.ydb_database = os.environ["YDB_DATABASE"]
    self.ydb_docs_table_name = os.environ["YDB_DOCS_TABLE_NAME"]
terraform {
  required_providers {
    yandex = {
      source = "yandex-cloud/yandex"
    }
  }
  required_version = ">= 0.13"
}

provider "yandex" {
  zone = var.zone
}

// ydb
resource "yandex_ydb_database_serverless" "ydb" {
  name      = "${var.prefix}-ydb"
  folder_id = var.folder_id
  serverless_database {
    storage_size_limit = 1
  }
}

resource "yandex_ydb_table" "docs_table" {
  path              = "${var.prefix}_docs_table"
  connection_string = yandex_ydb_database_serverless.ydb.ydb_full_endpoint

  column {
    name     = "doc_id"
    type     = "UUID"
    not_null = true
  }
  column {
    name     = "name"
    type     = "Utf8"
    not_null = true
  }
  column {
    name     = "url"
    type     = "Utf8"
    not_null = true
  }
  primary_key = ["doc_id"]
}

// sa
resource "yandex_iam_service_account" "sa" {
  folder_id = var.folder_id
  name      = "${var.prefix}-tf-sa"
}

resource "yandex_resourcemanager_folder_iam_member" "sa_editor" {
  folder_id = var.folder_id
  role      = "editor"
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
}

resource "yandex_iam_service_account_api_key" "sa_api_key" {
  service_account_id = yandex_iam_service_account.sa.id
}

resource "yandex_ydb_database_iam_binding" "sa_ydb_viewer" {
  database_id = yandex_ydb_database_serverless.ydb.id
  role        = "ydb.viewer"

  members = [
    "serviceAccount:${yandex_iam_service_account.sa.id}",
  ]
}

// bucket
resource "yandex_resourcemanager_folder_iam_member" "sa_storage_admin" {
  folder_id = var.folder_id
  role      = "storage.admin"
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
}

resource "yandex_iam_service_account_static_access_key" "sa_static_key" {
  service_account_id = yandex_iam_service_account.sa.id
  description        = "static access key for object storage"
}

resource "yandex_storage_bucket" "bucket" {
  bucket     = "${var.prefix}-temp"
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
  depends_on = [yandex_resourcemanager_folder_iam_member.sa_storage_admin]
}

// queue
resource "yandex_resourcemanager_folder_iam_member" "sa_ymq_admin" {
  folder_id = var.folder_id
  role      = "ymq.admin"
  member    = "serviceAccount:${yandex_iam_service_account.sa.id}"
}

resource "yandex_message_queue" "deadletter_queue" {
  name       = "${var.prefix}-deadletter-queue"
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
  depends_on = [yandex_resourcemanager_folder_iam_member.sa_ymq_admin]
}

// download: queue -> trigger -> function
resource "yandex_message_queue" "download_queue" {
  name                       = "${var.prefix}-download-queue"
  visibility_timeout_seconds = 60
  receive_wait_time_seconds  = 20
  redrive_policy = jsonencode({
    deadLetterTargetArn = yandex_message_queue.deadletter_queue.arn
    maxReceiveCount     = 3
  })
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}
data "yandex_message_queue" "download_queue" {
  name       = yandex_message_queue.download_queue.name
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

resource "yandex_function_trigger" "download_trigger" {
  name      = "${var.prefix}-download-trigger"
  folder_id = var.folder_id
  message_queue {
    queue_id           = yandex_message_queue.download_queue.arn
    batch_cutoff       = "2"
    batch_size         = 1
    service_account_id = yandex_iam_service_account.sa.id
  }
  function {
    id                 = yandex_function.download.id
    service_account_id = yandex_iam_service_account.sa.id
  }
}

data "archive_file" "download_zip" {
  type        = "zip"
  output_path = "function-download.zip"
  source_dir  = "../src/download"

  excludes = ["__pycache__", "*.pyc", ".DS_Store", ".env", ".python-version", ".venv", "uv.lock"]
}

resource "yandex_function" "download" {
  name               = "${var.prefix}-download"
  description        = "Функция получает сообщение с очереди, скачивает в s3 и сохраняет метаданные в YDB"
  user_hash          = data.archive_file.download_zip.output_sha256
  runtime            = "python312"
  entrypoint         = "main.handler"
  memory             = "1024"
  execution_timeout  = "60"
  folder_id          = var.folder_id
  service_account_id = yandex_iam_service_account.sa.id
  content {
    zip_filename = data.archive_file.download_zip.output_path
  }
  environment = {
    YDB_ENDPOINT          = "grpcs://${yandex_ydb_database_serverless.ydb.ydb_api_endpoint}"
    YDB_DATABASE          = yandex_ydb_database_serverless.ydb.database_path
    YDB_DOCS_TABLE_NAME   = yandex_ydb_table.docs_table.path
    AWS_ACCESS_KEY_ID     = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    S3_BUCKET_NAME        = yandex_storage_bucket.bucket.bucket
  }
}

// fetch-ydb: function
data "archive_file" "fetch_ydb_zip" {
  type        = "zip"
  output_path = "function-fetch-ydb.zip"
  source_dir  = "../src/fetch-ydb"

  excludes = ["__pycache__", "*.pyc", ".DS_Store", ".env", ".python-version", ".venv", "uv.lock"]
}

resource "yandex_function" "fetch_ydb" {
  name               = "${var.prefix}-fetch-ydb"
  description        = "Функция возвращает все метаданные с YDB"
  user_hash          = data.archive_file.fetch_ydb_zip.output_sha256
  runtime            = "python312"
  entrypoint         = "main.handler"
  memory             = "256"
  execution_timeout  = "60"
  folder_id          = var.folder_id
  service_account_id = yandex_iam_service_account.sa.id
  content {
    zip_filename = data.archive_file.fetch_ydb_zip.output_path
  }
  environment = {
    YDB_ENDPOINT        = "grpcs://${yandex_ydb_database_serverless.ydb.ydb_api_endpoint}"
    YDB_DATABASE        = yandex_ydb_database_serverless.ydb.database_path
    YDB_DOCS_TABLE_NAME = yandex_ydb_table.docs_table.path
  }
}

// gateway
resource "yandex_api_gateway" "docs_gateway" {
  name      = "${var.prefix}-gateway"
  folder_id = var.folder_id

  spec = templatefile("./gateway_spec.yaml.tpl", {
    api_name = "${var.prefix}-api"

    folder_id          = var.folder_id
    bucket_name        = yandex_storage_bucket.bucket.bucket
    service_account_id = yandex_iam_service_account.sa.id

    download_queue_url    = data.yandex_message_queue.download_queue.url
    ydb_db                = yandex_ydb_database_serverless.ydb.database_path
    docs_table_name       = yandex_ydb_table.docs_table.path
    fetch_ydb_function_id = yandex_function.fetch_ydb.id
  })

  depends_on = [yandex_ydb_database_iam_binding.sa_ydb_viewer]
}

output "api_gateway_url" {
  value       = yandex_api_gateway.docs_gateway.domain
  description = "API Gateway URL"
}
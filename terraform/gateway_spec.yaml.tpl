openapi: 3.0.0
info:
  title: ${api_name}
  version: 1.0.0
paths:
  /upload:
    post:
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - url
                - name
              properties:
                url:
                  type: string
                  format: uri
                  description: The URL of the file to upload
                  example: "https://example.com/file.pdf"
                name:
                  type: string
                  description: The name for the uploaded file
                  example: "document.pdf"
              additionalProperties: false
      x-yc-apigateway-integration:
        queue_url: ${download_queue_url}
        action: SendMessage
        folder_id: ${folder_id}
        type: cloud_ymq
        payload_format_type: body
        service_account_id: ${service_account_id}

  /document/{key}:
    get:
      parameters:
        - in: path
          name: key
          schema:
            type: string
          required: true
      x-yc-apigateway-integration:
        type: object_storage
        bucket: ${bucket_name}
        object: '{key}'
        service_account_id: ${service_account_id}

  /documents:
    get:
      description: Get docs
      # не работает
      # x-yc-apigateway-integration:
      #   type: cloud_ydb
      #   action: Scan
      #   database: ${ydb_db}
      #   table_name: ${docs_table_name}
      #   service_account_id: ${service_account_id}
      x-yc-apigateway-integration:
        type: cloud_functions
        function_id: ${fetch_ydb_function_id}
        service_account_id: ${service_account_id}
        timeout_ms: 30000
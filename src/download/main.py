import json
import logging
import boto3
import boto3.exceptions
import boto3.session
import ydb
import uuid
from dotenv import load_dotenv
from config import Config
import requests
from io import BytesIO

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def add_doc_to_db(config: Config, name: str, url: str) -> str:
    logger.info(f"Saving to database")

    id = uuid.uuid4()

    driver_config = ydb.DriverConfig(
        config.ydb_endpoint, 
        config.ydb_database, 
        credentials=ydb.credentials_from_env_variables(),
        root_certificates=ydb.load_ydb_root_certificate(),
    )

    with ydb.Driver(driver_config) as driver:
        try:
            driver.wait(timeout=5)
            with ydb.QuerySessionPool(driver) as pool:
                pool.execute_with_retries(
                    f"""
                    UPSERT INTO `{config.ydb_docs_table_name}` (
                        doc_id, name, url
                    ) VALUES (
                        $docId,
                        $name,
                        $url
                    );
                    """,
                    {
                        "$docId": (id, ydb.PrimitiveType.UUID),
                        "$name": (name, ydb.PrimitiveType.Utf8),
                        "$url": (url, ydb.PrimitiveType.Utf8),
                    }
                )
        except TimeoutError:
            logger.warning(f"Connect failed to YDB. Last reported errors by discovery: {driver.discovery_debug_details()}")
            exit(1)
    return str(id)


def download_doc_to_s3(config: Config, doc_id: str, url: str) -> str:
    logger.info(f"Downloading {url} to bucket {config.s3_bucket_name}")
        
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        session = boto3.session.Session()
        s3 = session.client(
            service_name='s3',
            endpoint_url="https://storage.yandexcloud.net",
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )
        
        file_buffer = BytesIO(response.content)
        s3.upload_fileobj(
            file_buffer,
            config.s3_bucket_name,
            doc_id,
            ExtraArgs={'ContentType': response.headers.get('content-type', 'application/octet-stream')}
        )

        return doc_id
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download from URL: {str(e)}")
        raise Exception(f"Video download failed: {str(e)}")
    except boto3.exceptions.S3UploadFailedError as e:
        logger.error(f"S3 upload failed: {str(e)}")
        raise Exception(f"S3 upload failed: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to download URL and upload object to S3: {str(e)}")
        raise


def handler(event, context):
    try:
        logger.info(f"Event: {json.dumps(event, ensure_ascii=False)}")
        load_dotenv(".env")
        config = Config()
        
        for message in event["messages"]:
            body = json.loads(message['details']['message']['body'])
            name = body['name']
            url = body['url']

            if not name or not url:
                return { 
                    'statusCode': 400,  
                    'headers': {
                        'Content-Type': 'text/plain'
                    },
                    'body': 'name or url are not set' 
                }
            
            logger.info(f"Received data: name={name}, url={url}")
            
            doc_id = add_doc_to_db(config, name, url)

            download_doc_to_s3(config, doc_id, url)

        return { 'statusCode': 200 }
        
    except Exception as e:
        logger.error(f"Error in handler: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'text/plain'
            },
            'body': f'Error occurred: {str(e)}'
        }

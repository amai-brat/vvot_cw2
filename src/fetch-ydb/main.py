import json
import logging
import ydb
from dotenv import load_dotenv
from config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_docs(config: Config) -> list[dict]:
    driver_config = ydb.DriverConfig(
        config.ydb_endpoint, 
        config.ydb_database, 
        credentials=ydb.credentials_from_env_variables(),
        root_certificates=ydb.load_ydb_root_certificate(),
    )

    logger.info(f"Getting metadata from database")
    with ydb.Driver(driver_config) as driver:
        try:
            driver.wait(timeout=5)
            with ydb.QuerySessionPool(driver) as pool:
                result_sets = pool.execute_with_retries(
                    f"""
                    SELECT doc_id, name, url
                    FROM `{config.ydb_docs_table_name}`
                    """
                )

                result = []
                for row in result_sets[0].rows:
                    doc = {
                        'doc_id': str(row.doc_id), 
                        'name': row.name, 
                        'url': row.url
                    }
                    result.append(doc)
                return result
            
        except TimeoutError:
            logger.warning(f"Connect failed to YDB. Last reported errors by discovery: {driver.discovery_debug_details()}")
            exit(1)


def handler(event, context):
    try:
        logger.info(f"Event: {json.dumps(event, ensure_ascii=False)}")
        load_dotenv(".env")
        config = Config()

        docs = get_docs(config)
        body = json.dumps({'docs': docs}, ensure_ascii=False)

        return { 
            'statusCode': 200, 
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': body
        }
        
    except Exception as e:
        logger.error(f"Error in handler: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'text/plain'
            },
            'body': f'Error occurred: {str(e)}'
        }
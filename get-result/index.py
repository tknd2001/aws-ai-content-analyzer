import json
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('aif-content-analyzer-results')

def lambda_handler(event, context):
    file_key = event.get('queryStringParameters', {}).get('fileKey') if event.get('queryStringParameters') else None

    if not file_key:
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Missing fileKey query parameter'})
        }

    response = table.get_item(Key={'fileKey': file_key})
    item = response.get('Item')

    if not item:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'No record found for this fileKey'})
        }

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(item)
    }

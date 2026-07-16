import json
import boto3
import uuid

rekognition = boto3.client('rekognition')
bedrock = boto3.client('bedrock-runtime')
polly = boto3.client('polly')
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('aif-content-analyzer-results')

def lambda_handler(event, context):
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        print(f"New file uploaded: s3://{bucket}/{key}")

        # Skip audio files this function itself creates (avoid infinite loop)
        if key.startswith('audio/'):
            print(f"Skipping self-generated audio file: {key}")
            continue

        if not key.lower().endswith(('.png', '.jpg', '.jpeg')):
            print(f"Skipping non-image file: {key}")
            continue

        image_ref = {'S3Object': {'Bucket': bucket, 'Name': key}}

        # 1. Content moderation check
        moderation_response = rekognition.detect_moderation_labels(
            Image=image_ref,
            MinConfidence=75
        )
        moderation_labels = moderation_response.get('ModerationLabels', [])

        if moderation_labels:
            print(f"Content flagged, skipping further processing: {moderation_labels}")
            continue

        # 2. Label detection — tightened to reduce noisy/overlapping labels
        label_response = rekognition.detect_labels(
            Image=image_ref,
            MaxLabels=5,
            MinConfidence=85
        )
        labels = [l['Name'] for l in label_response['Labels']]
        print(f"Detected labels: {labels}")

        # 3. Generate caption with Bedrock (Nova Lite) — prompt fixed to avoid
        # treating overlapping labels as separate objects AND to avoid
        # inventing unstated context (setting/background/surface)
        prompt = f"""You are an assistant that writes short, accurate image captions.

An image analysis tool detected these possible elements, which may overlap or describe the same object rather than separate items: {', '.join(labels)}

Write one concise, natural sentence describing what the image most likely shows.
Rules:
- Assume the labels may describe the same single object from different angles or categories - do not assume multiple distinct objects unless the labels clearly indicate different types of things.
- Do NOT invent a setting, background, surface, or context (e.g. "on a table," "outdoors," "in a room") unless it is explicitly one of the detected elements. If no setting is detected, describe the object on its own without implying a location.
- Do not mention "labels," "detected elements," or the analysis process - just describe the scene naturally."""

        bedrock_response = bedrock.invoke_model(
            modelId='amazon.nova-lite-v1:0',
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"text": prompt}
                        ]
                    }
                ],
                "inferenceConfig": {
                    "maxTokens": 100,
                    "temperature": 0.7,
                    "topP": 0.9
                }
            })
        )

        response_body = json.loads(bedrock_response['body'].read())
        caption = response_body['output']['message']['content'][0]['text']
        print(f"Generated caption: {caption}")

        # 4. Convert caption to speech with Polly
        polly_response = polly.synthesize_speech(
            Text=caption,
            OutputFormat='mp3',
            VoiceId='Joanna'
        )

        audio_key = f"audio/{key.rsplit('.', 1)[0]}.mp3"
        s3.put_object(
            Bucket=bucket,
            Key=audio_key,
            Body=polly_response['AudioStream'].read(),
            ContentType='audio/mpeg'
        )
        print(f"Audio saved to: s3://{bucket}/{audio_key}")

        # 5. Store the full record in DynamoDB
        table.put_item(
            Item={
                'fileKey': key,
                'id': str(uuid.uuid4()),
                'labels': labels,
                'caption': caption,
                'audioKey': audio_key,
                'bucket': bucket
            }
        )
        print(f"Record saved to DynamoDB for {key}")

    return {
        'statusCode': 200,
        'body': json.dumps('Processed successfully')
    }

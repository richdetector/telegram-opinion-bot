from openai import OpenAI
import json

from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def ask_json(prompt, model="gpt-4.1-mini"):

    response = client.responses.create(
        model=model,
        input=prompt,
        text={
            "format": {
                "type": "json_object"
            }
        }
    )

    return json.loads(response.output_text)


def ask_text(prompt, model="gpt-4.1-mini"):

    response = client.responses.create(
        model=model,
        input=prompt
    )

    return response.output_text
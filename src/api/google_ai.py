from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import requests

class Ticket(BaseModel):
    total: float = Field(description="Cantidad total o Importe en pesos mexicanos (MXN) de combustible comprados.")
    quantity: float = Field(description="Cantidad total en litros(L) de combustible comprados.")
    date: str = Field(description="Fecha de la compra.")
    product: str= Field(description="Tipo de producto comprado.")
    station: int = Field(description="Código numérico identificador de la ESTACION. Se encuentra específicamente después de la palabra 'ESTACION'. NO CONSIDERAR el código que viene después de la frase 'ES ORIGEN' (este es el código de laestación origen no de la estación donde se hizo la carga.)")
    address: str = Field (description="Direccion de la estacion.")

client = genai.Client(vertexai=True, project="innovacion-futuro", location="us-central1")
prompt="""
Extrae la información del siguiente Ticket:
"""

def extraerInfo(imagen_ticket)->Ticket:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents = [prompt,
                    types.Part.from_bytes(data=imagen_ticket,mime_type="image/jpeg")],
        config = {
            "response_mime_type":"application/json",
            "response_json_schema":Ticket.model_json_schema(),
        },
    )

    ticket = Ticket.model_validate_json(response.text)

    return ticket

if __name__ == "__main__":
    img_url = "https://scontent-sea5-1.xx.fbcdn.net/v/t39.30808-6/626822586_122302866188010985_2325173877180364144_n.jpg?stp=cp1_dst-jpg_tt6&_nc_cat=105&ccb=1-7&_nc_sid=bd9a62&_nc_eui2=AeEI3Lx2wgckKLZOJLoBjH1WQwDIpPet-TJDAMik9635MpOdtPDkEFaUr2DZkAJzZ0twvyXAojb9N27zNhQy1QfE&_nc_ohc=SpYE9-5Xn3AQ7kNvwEXYkFG&_nc_oc=AdkLzofRdiGBBRSzlhit1nXdFh6ppZb3aMfbW_S70-QXVoh4i9UAlXETU6RfzO5E8QA&_nc_zt=23&_nc_ht=scontent-sea5-1.xx&edm=AOerShkEAAAA&_nc_gid=QRU3CvDmLQlXxJy1lpiJRA&_nc_tpa=Q5bMBQGdgQa87ab0v5TKlfD3pongOm0j2_Jr-xRapfdz22vfSTDrA1GOIwVRG39Nkw5EJV8d1aZagXoQ&oh=00_AfuwzFrstuIc5PdZWJgWw8jpDd5Lyhj2xSaonHoaWAGWSQ&oe=698EF63E"
    response_ticket_url = requests.get(img_url,timeout=20)
    response_ticket_url.raise_for_status()
    image_bytes = response_ticket_url.content

    resultado = extraerInfo(image_bytes)

    print(resultado)
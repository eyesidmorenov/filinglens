# Entregable 1: EDA del dataset

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate      # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Abre el `.env` y pega las llaves de solo lectura que vienen en el brief.

## Paso 1: explorar el bucket

```bash
python explore_s3.py
```

No descarga nada. Solo lista y te dice cómo está organizado el dataset:
cuántos archivos hay, cuánto pesan, qué estructura de carpetas usa,
qué años aparecen y si los nombres traen el ticker de la empresa.

Con esa salida decidimos qué muestra bajar y cómo sacar la metadata.

## Importante

El `.env` está en el `.gitignore`. Las llaves no pueden entrar al
repositorio, ni en el código, ni en un notebook, ni en el historial.

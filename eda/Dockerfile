# FilingLens EDA: exploración del dataset (entregable 1)
# Un contenedor que trae Python y todas las librerías del EDA ya instaladas.
# Por defecto abre Jupyter para ver el notebook; los scripts se corren a pedido.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt eda/requirements.txt
RUN pip install --no-cache-dir -r eda/requirements.txt

# El código del EDA va en eda/, como en el repo, para que las rutas sean las mismas.
# El .env con las llaves NUNCA entra a la imagen (lo bloquea .dockerignore).
COPY . eda/

# data/ se monta desde tu máquina con docker compose, nunca va dentro de la imagen
ENV PYTHONUNBUFFERED=1

EXPOSE 8888

# Jupyter sin contraseña: solo es seguro porque compose lo publica en 127.0.0.1
CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", \
     "--ServerApp.token=", "--ServerApp.password=", "--ServerApp.root_dir=/app"]

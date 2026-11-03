# Imagen de prueba `bootstrap`

Contrato: `docs/ARCHITECTURE.md` §5.11. Se construye y publica **una vez**, después del `apply` de INF-1.3 (que crea
los repositorios). Las etiquetas de ECR son inmutables: volver a subir `bootstrap` falla mientras exista (y si la
política de ECR la expira tras 5 imágenes nuevas, se vuelve a subir igual).

Desde `INFRASTRUCTURA_TERRAFORM/project/`, con Docker y el perfil de AWS de la persona:

```bash
REGISTRO=648617469176.dkr.ecr.us-east-1.amazonaws.com
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$REGISTRO"
docker build --platform linux/amd64 -t campus-locator-imagen-prueba pruebas/imagen-prueba
for repo in backend embedding; do
  docker tag campus-locator-imagen-prueba "$REGISTRO/campus-locator/$repo:bootstrap"
  docker push "$REGISTRO/campus-locator/$repo:bootstrap"
done
```

Prueba local: `docker run --rm -p 8000:8000 -p 8080:8080 campus-locator-imagen-prueba` y
`curl -s localhost:8000/v1/health localhost:8080/health/ready`; con `... campus-locator-imagen-prueba python -m app.cli
migrar` imprime `imagen de prueba: nada que migrar` y sale con 0.

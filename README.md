## Запуск
```bash
cd terraform
export YC_TOKEN=$(yc iam create-token)

terraform init
terraform apply \
  -var="cloud_id=<ваш_cloud_id>" \
  -var="folder_id=<ваш_folder_id>"
```

## Проверка
```bash
curl -X POST \
  -H 'Content-Type: application/json' \
  -d '{"name": "sample0", "url": "https://sakuya.su/cw02.pdf"}' \ 
  https://{api_gateway_url}/upload

curl https://{api_gateway_url}/documents
```
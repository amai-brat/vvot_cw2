variable "cloud_id" {
  type        = string
  description = "ID облака Yandex Cloud"
}

variable "folder_id" {
  type        = string
  description = "ID каталога Yandex Cloud"
}

variable "zone" {
  type        = string
  description = "Зона развёртывания"
  default     = "ru-central1-d"
}

variable "prefix" {
  type        = string
  description = "Префикс ресурсов"
  default     = "vvot-cw02"
}
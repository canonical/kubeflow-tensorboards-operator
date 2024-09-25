variable "app_name" {
  description = "Application name"
  type        = string
  default     = "tensorboards-web-app"
}

variable "channel" {
  description = "Charm channel"
  type        = string
  default     = "1.9/stable"
}

variable "config" {
  description = "Map of charm configuration options"
  type        = map(string)
  default     = {}
}

variable "model_name" {
  description = "Model name"
  type        = string
}

variable "resources" {
  description = "Map of resources"
  type        = map(string)
  default     = null
}

variable "revision" {
  description = "Charm revision"
  type        = number
  default     = null
}

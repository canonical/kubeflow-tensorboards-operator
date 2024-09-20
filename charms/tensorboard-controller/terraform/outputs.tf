output "app_name" {
  value = juju_application.tensorboard_controller.name
}

output "provides" {
  value = {
    metrics_endpoint  = "metrics-endpoint",
  }
}

output "requires" {
  value = {
    gateway_info = "gateway-info",
    logging      = "logging"
  }
}

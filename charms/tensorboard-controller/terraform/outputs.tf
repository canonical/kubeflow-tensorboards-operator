output "app_name" {
  value = juju_application.tensorboard_controller.name
}

output "provides" {
  value = {
    metrics_endpoint = "metrics-endpoint",
    provide_cmr_mesh = "provide-cmr-mesh"
  }
}

output "requires" {
  value = {
    gateway_info     = "gateway-info",
    gateway_metadata = "gateway-metadata",
    logging          = "logging",
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh"
  }
}

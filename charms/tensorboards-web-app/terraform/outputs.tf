output "app_name" {
  value = juju_application.tensorboards_web_app.name
}

output "provides" {
  value = {
    metrics_endpoint = "metrics-endpoint",
  }
}

output "requires" {
  value = {
    ingress         = "ingress",
    dashboard_links = "dashboard-links",
    logging         = "logging",
  }
}

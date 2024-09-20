resource "juju_application" "tensorboards_web_app" {
  charm {
    name     = "tensorboards-web-app"
    channel  = var.channel
    revision = var.revision
  }
  config    = var.config
  model     = var.model_name
  name      = var.app_name
  resources = var.resources
  trust     = true
  units     = 1
}

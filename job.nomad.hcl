variable "image_id" {
  type = string
}

job "valerie-bot" {
  datacenters = ["dc1"]
  type        = "service"

  group "app" {
    count = 1

    task "bot" {
      driver = "docker"

      config {
        image = var.image_id

        work_dir = "/app"

        mount {
          type   = "volume"
          source = "valerie-bot-data"
          target = "/app/storage"

          readonly = false

          volume_options {
            no_copy = true
          }
        }
      }

      resources {
        cpu    = 200
        memory = 256
      }
    }
  }
}

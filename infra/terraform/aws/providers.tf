provider "aws" {
  region = var.aws_region

  # Emülatör modunda sahte credential kullan ve gerçek AWS'ye hiç bağlanma
  access_key                  = var.use_local_emulator ? "test" : null
  secret_key                  = var.use_local_emulator ? "test" : null
  skip_credentials_validation = var.use_local_emulator
  skip_requesting_account_id  = var.use_local_emulator
  skip_metadata_api_check     = var.use_local_emulator

  dynamic "endpoints" {
    for_each = var.use_local_emulator ? [1] : []
    content {
      ec2 = var.emulator_endpoint
      sts = var.emulator_endpoint
    }
  }

  default_tags {
    tags = {
      Project   = "smart-fleet"
      ManagedBy = "terraform"
    }
  }
}

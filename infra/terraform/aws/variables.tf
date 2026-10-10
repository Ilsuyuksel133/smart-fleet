variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-central-1"
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
  default     = "t3.micro"
}

variable "allowed_cidrs" {
  description = "CIDR ranges allowed to reach SSH (22), the API (8000) and Grafana (3000). No default on purpose."
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0 && alltrue([for c in var.allowed_cidrs : can(cidrhost(c, 0))])
    error_message = "allowed_cidrs must contain at least one valid CIDR range."
  }

  validation {
    condition     = !contains(var.allowed_cidrs, "0.0.0.0/0")
    error_message = "Opening the instance to the whole internet (0.0.0.0/0) is not allowed."
  }
}

variable "image_tag" {
  description = "Immutable GHCR image tag to deploy (e.g. sha-1a2b3c4), passed to the Ansible playbook."
  type        = string

  validation {
    condition     = var.image_tag != "latest"
    error_message = "Use an immutable tag such as sha-1a2b3c4, not \"latest\"."
  }
}

variable "ami_id" {
  description = "AMI to use. When null, the latest Ubuntu 24.04 AMI from Canonical is looked up."
  type        = string
  default     = null
}

variable "key_name" {
  description = "Name of an existing EC2 key pair for SSH access (optional)."
  type        = string
  default     = null
}

variable "repo_url" {
  description = "Git repository cloned by cloud-init on first boot."
  type        = string
  default     = "https://github.com/Ilsuyuksel133/smart-fleet.git"
}

variable "repo_ref" {
  description = "Git branch or tag checked out by cloud-init."
  type        = string
  default     = "main"
}

variable "use_local_emulator" {
  description = "Send all AWS API calls to a local emulator (Moto) with fake credentials instead of real AWS."
  type        = bool
  default     = false
}

variable "emulator_endpoint" {
  description = "Endpoint of the local AWS emulator, used when use_local_emulator is true."
  type        = string
  default     = "http://localhost:5000"
}

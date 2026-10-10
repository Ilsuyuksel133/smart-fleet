# --- Ağ: VPC, public subnet, internet gateway, route table ---

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "smart-fleet-vpc" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = { Name = "smart-fleet-public" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "smart-fleet-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0" # internete çıkış (giriş değil)
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "smart-fleet-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# --- Güvenlik: sadece izin verilen IP aralıklarından 22 / 8000 / 3000 ---

locals {
  ingress_ports = {
    ssh     = 22
    api     = 8000
    grafana = 3000
  }

  ingress_rules = {
    for pair in setproduct(keys(local.ingress_ports), var.allowed_cidrs) :
    "${pair[0]}-${pair[1]}" => { port = local.ingress_ports[pair[0]], cidr = pair[1] }
  }
}

resource "aws_security_group" "app" {
  name        = "smart-fleet-app"
  description = "smart-fleet: SSH, API and Grafana from allowed CIDRs only"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "smart-fleet-app" }
}

resource "aws_vpc_security_group_ingress_rule" "app" {
  for_each = local.ingress_rules

  security_group_id = aws_security_group.app.id
  description       = "Allow ${each.key}"
  ip_protocol       = "tcp"
  from_port         = each.value.port
  to_port           = each.value.port
  cidr_ipv4         = each.value.cidr
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.app.id
  description       = "Outbound traffic (apt, GHCR, GitHub)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# --- EC2 instance ---

data "aws_ami" "ubuntu" {
  count = var.ami_id == null ? 1 : 0

  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_instance" "app" {
  ami                    = coalesce(var.ami_id, try(data.aws_ami.ubuntu[0].id, null))
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.app.id]
  key_name               = var.key_name

  # İlk açılışta: repoyu çek ve Ansible playbook'unu bu makinenin kendisine uygula
  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    repo_url  = var.repo_url
    repo_ref  = var.repo_ref
    image_tag = var.image_tag
  })

  metadata_options {
    http_tokens = "required" # IMDSv2
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "smart-fleet" }
}

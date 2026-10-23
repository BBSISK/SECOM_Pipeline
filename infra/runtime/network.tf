# Runtime network (SECOM-21).
#
# A small VPC for the producer (ECS Fargate) and, later, the processor. Everything here
# is free: VPC, subnets, internet gateway, route table, S3 gateway endpoint and security
# groups have no hourly charge. Deliberately NO NAT gateway (billed per hour even when idle).
#
# Without NAT, a task reaches AWS services (Kinesis, ECR, CloudWatch Logs) through the
# internet gateway, so the producer task gets a public IPv4 address when it starts
# (assign_public_ip on the ECS service, SECOM-25). Subnets don't hand out public IPs by
# default, and nothing is allowed in: the producer security group has no inbound rules.

locals {
  name_prefix = "secom"
  vpc_cidr    = "10.20.0.0/16"
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = local.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.name_prefix}-vpc" }
}

# Two subnets in different availability zones, so a later service can spread across them.
resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(local.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false # tasks ask for a public IP explicitly; nothing gets one by default

  tags = { Name = "${local.name_prefix}-public-${count.index}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name_prefix}-public" }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# S3 traffic (raw zone, SECOM-26) stays on the AWS network instead of the internet. Gateway endpoints are free.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id]

  tags = { Name = "${local.name_prefix}-s3" }
}

# The VPC's default security group allows all traffic between its members. Strip every rule
# so nothing can use it by accident; resources must name a security group of their own.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-default-locked" }
}

# Producer: nothing in, HTTPS out only (Kinesis, ECR, CloudWatch Logs, S3 are all HTTPS APIs).
resource "aws_security_group" "producer" {
  name        = "${local.name_prefix}-producer"
  description = "Replay producer task: no inbound, outbound HTTPS only"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-producer" }
}

resource "aws_vpc_security_group_egress_rule" "producer_https" {
  security_group_id = aws_security_group.producer.id
  description       = "HTTPS to AWS service APIs (no NAT, so via the internet gateway)"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

output "vpc_id" {
  description = "Runtime VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Subnets for the producer task (and later the processor)."
  value       = aws_subnet.public[*].id
}

output "producer_security_group_id" {
  description = "Security group for the producer task: no inbound, HTTPS out."
  value       = aws_security_group.producer.id
}

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 6.0.0"
    }
  }
}

variable "compartment_ocid" {}
variable "preflight_group_name" { default = "oci-capacity-preflight" }

resource "oci_ons_notification_topic" "capacity" {
  compartment_id = var.compartment_ocid
  name           = "oci-capacity-preflight"
  description    = "Capacity risk and preflight notifications"
}

resource "oci_objectstorage_bucket" "snapshots" {
  compartment_id = var.compartment_ocid
  name           = "oci-capacity-preflight-snapshots"
  namespace      = "replace-with-namespace"
}

# Deploy function image and API Gateway routes /preflight, /preflight/batch, /risk
# after pushing the container image to OCIR.

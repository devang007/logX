// Environment-level config shared by all units under llms4all/.
// Read by root.hcl via find_in_parent_folders("account.hcl").

locals {
  // S3 bucket for OpenTofu state for this environment.
  state_bucket_name = "logx-tf-state-j06g0x"
}

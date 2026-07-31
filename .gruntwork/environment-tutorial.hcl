// Pipelines environment config for the auth-less "tutorial" tutorial environment.
// Pipelines reads all .hcl files in .gruntwork/. This environment intentionally has NO cloud
// authentication: units under it (a self-contained null_resource tutorial unit with local state)
// plan/apply with no cloud credentials. The real cloud OIDC config is added later by the
// "Connect to your cloud" wizard (the cloud-config template) once the customer authorizes their cloud.

environment "tutorial" {  
  filter {
    paths = ["tutorial/*"]
  }

  authentication {}
}

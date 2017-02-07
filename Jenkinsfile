#!groovy
pipeline {
  agent any

  stages {
    stage('Prepare') {
      steps {
        node('master') {
          // TODO: This might be a bottleneck, but that's ok for now!
          sh 'echo "Starting the build..."'
          sh 'echo "It it always nice to have a green checkmark :D"'
        }
      }
    }

    stage('Test') {
      steps {
        parallel commonlib_unit: {
          timeout(time: 55, unit: 'MINUTES') {
            node('worker-ami') {
              checkout scm

              sh 'bash -c "TEST_SUITE=commonlib-unit ./scripts/all-tests.sh"'

              archiveArtifacts 'reports/**, test_root/log/**'
              junit 'reports/**/*.xml'
            }
          }
        }, lms_unit_4: {
          timeout(time: 55, unit: 'MINUTES') {
            node('worker-ami') {
              checkout scm

              sh 'bash -c "TEST_SUITE=lms-unit SHARD=4 ./scripts/all-tests.sh"'

              archiveArtifacts 'reports/**, test_root/log/**'
              junit 'reports/**/*.xml'
            }
          }
        }
      }
    }

    stage('Done') {
      steps {
        node('master') {
          // TODO: This might be a bottleneck, but that's ok for now!
          sh 'echo "I am done, hurray!"'
        }
      }
    }
  }
}

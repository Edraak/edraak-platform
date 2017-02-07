#!groovy

def makeNode(suite, shard) {
  return {
    node('worker-ami') {
      timeout(time: 55, unit: 'MINUTES') {
        checkout scm
        sh 'git log --oneline | head'

        echo "Hi, it is me ${suite}:${shard} again, the worker just started!"

        try {
          withEnv(["TEST_SUITE=${suite}", "SHARD=${shard}"]) {
            sh './scripts/all-tests.sh'
          }
        } finally {
          archiveArtifacts 'reports/**, test_root/log/**'
          junit 'reports/**/*.xml'
        }
      }
    }
  }
}

def getSuites() {
  return [
    // [name: 'js-unit', 'shards': ['all']],
    [name: 'commonlib-unit', 'shards': ['all']],
    // [name: 'quality', 'shards': ['all']],
    [name: 'lms-unit', 'shards': [
      // 1,
      // 2,
      // 3,
      4,
    ]],
    // [name: 'cms-unit', 'shards': ['all']],
    // [name: 'lms-acceptance', 'shards': ['all']],
    // [name: 'cms-acceptance', 'shards': ['all']],
    [name: 'bok-choy', 'shards': [
      // 1,
      // 2,
      // 3,
      // 4,
      // 5,
      // 6,
      // 7,
      // 8,
      // 9,
    ]],
  ]
}

def buildParallelSteps() {
  def parallelSteps = [:]

  for (def suite in getSuites()) {
    def name = suite['name']

    for (def shard in suite['shards']) {
      parallelSteps["${name}_${shard}"] = makeNode(name, shard)
    }
  }

  return parallelSteps
}

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
        parallel buildParallelSteps()
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

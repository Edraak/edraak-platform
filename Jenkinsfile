#!groovy

def stepsForParallel = [:]
def ENABLE_BOK_CHOY = false

stage('Prepare') {
  def makeNode = { suite, shard ->
    return {
      echo "I am ${suite}:${shard}, and the worker is yet to be started!"

      node('worker-ami') {
        timeout(time: 55, unit: 'MINUTES') {
          echo "Hi, it is me ${suite}:${shard} again, the workeer just started!"

          git 'https://github.com/Edraak/jenkins-edx-platform.git'

          withEnv(["TEST_SUITE=${suite}", "SHARD=${shard}"]) {
            sh './scripts/all-tests.sh'
          }
        }

        archiveArtifacts 'reports/*, test_root/log/*'
      }
    }
  }

  def suites = [
    [name: 'quality', 'shards': 1],
    [name: 'lms-unit', 'shards': 4],
    [name: 'cms-unit', 'shards': 1],
    [name: 'commonlib-unit', 'shards': 1],
    [name: 'js-unit', 'shards': 1],
    [name: 'commonlib-js-unit', 'shards': 1],
    [name: 'lms-acceptance', 'shards': 1],
    [name: 'cms-acceptance', 'shards': 1],
  ]

  if (ENABLE_BOK_CHOY) {
    suites.add([name: 'bok-choy', 'shards': 9])
  }

  for (def suite in suites) {
    def name = suite['name']
    def shards = suite['shards']

    if (shards == 1) {
      stepsForParallel["${name}_all"] = makeNode(name, 'all')
    } else {
      for (int i=1; i<=shards; i++) {
        stepsForParallel["${name}_shard_${i}"] = makeNode(name, i)
      }
    }
  }

  echo 'Starting the build...'
}

stage('Test') {
  parallel stepsForParallel
}

stage('Done') {
  echo 'I am done, hurray!'
}

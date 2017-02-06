#!groovy

def stepsForParallel = [:]
def ENABLE_BOK_CHOY = false
def RUN_ONLY_JS_UNIT_AND_COMMONLIB = true

def makeNode(suite, shard) {
  return {
    echo "I am ${suite}:${shard}, and the worker is yet to be started!"

    node('worker-ami') {
      timeout(time: 55, unit: 'MINUTES') {
        echo "Hi, it is me ${suite}:${shard} again, the worker just started!"

        git 'https://github.com/Edraak/jenkins-edx-platform.git'

        withEnv(["TEST_SUITE=${suite}", "SHARD=${shard}"]) {
          sh './scripts/all-tests.sh'
        }
      }

      archiveArtifacts 'reports/*, test_root/log/*'
    }
  }
}

def getSuites() {
  def suites = [
    [name: 'js-unit', 'shards': 1],
    [name: 'commonlib-unit', 'shards': 1],
  ]

  if (!RUN_ONLY_JS_UNIT_AND_COMMONLIB) {
    suites.addAll([
      [name: 'quality', 'shards': 1],
      [name: 'lms-unit', 'shards': 4],
      [name: 'cms-unit', 'shards': 1],
      [name: 'lms-acceptance', 'shards': 1],
      [name: 'cms-acceptance', 'shards': 1],
    ])
  }

  if (ENABLE_BOK_CHOY && !RUN_ONLY_JS_UNIT_AND_COMMONLIB) {
    suites.add([name: 'bok-choy', 'shards': 9])
  }

  return suites
}

def buildParallelSteps() {
  for (suite in getSuites()) {
    def name = suite['name']
    def shards = suite['shards']

    if (shards > 1) {
      for (int i=1; i<=shards; i++) {
        stepsForParallel["${name}_shard_${i}"] = makeNode(name, i)
      }
    } else {
      stepsForParallel["${name}_all"] = makeNode(name, 'all')
    }
  }
}

stage('Prepare') {
  buildParallelSteps()
  echo 'Starting the build...'
}

stage('Test') {
  parallel stepsForParallel
}

stage('Done') {
  echo 'I am done, hurray!'
}

from v10.core import ROOT, verify_release
if __name__ == '__main__':
    print(verify_release(ROOT/'current')['release_id'])

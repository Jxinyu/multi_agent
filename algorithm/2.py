from typing import List


class Solution:
    def groupAnagrams(self, strs: List[str]) -> List[List[str]]:
        d = {}
        for i in strs:
            s = list(i)
            s.sort()
            l = len(s)
            si = ''.join(set(s)) + str(l)
            if si in d.keys():
                d[si].append(i)
            else:
                d[si] = [i]
        res = list(d.values())
        return res


if __name__ == '__main__':
    print(Solution().groupAnagrams(["a"]))

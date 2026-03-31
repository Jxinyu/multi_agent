from typing import List


class Solution:
    def trap(self, height: List[int]) -> int:
        n = len(height)
        s = [[0, height[0]]]  # 单调栈
        index = 1
        res = 0
        while index < n:
            if s and height[index] <= s[-1][1]:  # insert stack
                s.append([index, height[index]])
                index += 1
                continue
            pop = []
            while s and s[-1][1] < height[index]:  # pop stack
                pop.append(s.pop())

            t = s[-1][1] if s else (pop.pop())[1]

            min_v = min(height[index], t)
            while pop:  # calculate
                res += max(0, (min_v - (pop.pop())[1]))
            s.append([index, height[index]])
            index += 1
        return res


if __name__ == '__main__':
    # [0, 1, 0, 2, 1, 0, 1, 3, 2, 1, 2, 1]
    # print(Solution().trap([4, 2, 3, 3]))
    # 0 1 1 2 2 2 2 3 3 3 3 3
    # 3 3 3 3 3 3 3 3 2 2 2 1
    # 0 1 0 2 1 0 1 3 2 1 2 1
    # 0 0 1 0 1 2 1 0 0 1 0 0
    print(Solution().trap([0, 1, 0, 2, 1, 0, 1, 3, 2, 1, 2, 1]))
